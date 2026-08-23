import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from flask import Blueprint, redirect, render_template, request, jsonify, url_for
from pydantic import ValidationError

from config.reload import classify_settings_delta
from config.settings import (
    UPDATABLE_DASHBOARD_KEYS,
    apply_config_payload,
    apply_dashboard_update,
    config_schema,
    environment_override,
    list_config_backups,
    load_settings,
    restore_config_backup,
    save_settings,
    settings_to_dashboard_dict,
    validation_field_errors,
    yaml_environment,
)
from modules.BinanceClient import BinanceClient
from modules.logging_setup import LOG_JSON_FILE, log_event, read_structured_logs
from persistence.process_lock import lock_path_for
from persistence.state_store import DEFAULT_DB_PATH, StateStore
from security import (
    client_key,
    csrf_valid,
    end_session,
    ensure_csrf_token,
    is_authenticated,
    login_blocked_for,
    register_failed_login,
    reset_login_attempts,
    safe_redirect_target,
    session_auth_enabled,
    start_session,
    verify_password,
)
from services.order_sync import DEFAULT_PROFIT_CUTOFF, sync_filled_orders_from_binance
from services.outcome_history import (
    META_REBUILT,
    build_outcome_board,
    kind_hints_from_log,
    match_trades_and_open_lots,
    rebuild_outcomes_from_orders,
)
from services.portfolio import fetch_portfolio

routes = Blueprint("routes", __name__)

_PORTFOLIO_CACHE_TTL = 5.0
_HISTORY_CACHE_TTL = 30.0
_portfolio_lock = threading.Lock()
_portfolio_cache = {"ts": 0.0, "data": None}
_history_lock = threading.Lock()
_history_cache = {"ts": 0.0, "data": None}
_spot_client = None
_spot_client_key = None


def _create_spot_client(api_key: str, secret_key: str, testnet: bool):
    return BinanceClient(
        api_key,
        secret_key,
        sync=True,
        ping=False,
        verbose=False,
        testnet=testnet,
    )


def get_spot_client(api_key: str, secret_key: str, testnet: bool):
    global _spot_client, _spot_client_key
    key = (api_key, secret_key, testnet)
    with _portfolio_lock:
        if _spot_client is None or _spot_client_key != key:
            _spot_client = _create_spot_client(api_key, secret_key, testnet)
            _spot_client_key = key
        return _spot_client


def _last_buy_prices(assets) -> dict:
    store = StateStore()
    prices = {}
    for asset in assets:
        state = store.load_state(asset.operation_code)
        prices[asset.operation_code] = float(state.last_buy_price or 0)
    return prices


def get_portfolio_snapshot():
    now = time.time()
    with _portfolio_lock:
        cached = _portfolio_cache["data"]
        if cached is not None and now - _portfolio_cache["ts"] < _PORTFOLIO_CACHE_TTL:
            return cached

    settings, env = load_settings()
    if not env.api_key or not env.secret_key:
        raise ValueError("Credenciais da Binance não configuradas")

    client = get_spot_client(
        env.api_key,
        env.secret_key,
        testnet=settings.environment == "testnet",
    )
    snapshot = fetch_portfolio(
        client,
        settings.assets,
        last_buy_prices=_last_buy_prices(settings.assets),
    )
    with _portfolio_lock:
        _portfolio_cache["ts"] = time.time()
        _portfolio_cache["data"] = snapshot
    return snapshot


def get_profit_board(force_refresh: bool = False):
    now = time.time()
    with _history_lock:
        cached = _history_cache["data"]
        if (
            not force_refresh
            and cached is not None
            and now - _history_cache["ts"] < _HISTORY_CACHE_TTL
        ):
            return cached

    # Sync/rebuild outside the lock so Binance latency does not block other readers.
    store = StateStore()
    settings, env = load_settings()
    take_profit_at = [float(level.at) for level in settings.risk.take_profit]
    stop_loss_pct = float(settings.risk.stop_loss_pct or 0)
    sync_info = {"inserted": 0, "scanned": 0, "cutoff": DEFAULT_PROFIT_CUTOFF}

    if env.api_key and env.secret_key:
        client = get_spot_client(
            env.api_key,
            env.secret_key,
            testnet=settings.environment == "testnet",
        )
        sync_info = sync_filled_orders_from_binance(
            client,
            store,
            [asset.operation_code for asset in settings.assets],
            cutoff_iso=DEFAULT_PROFIT_CUTOFF,
        )

    force_rebuild = (
        force_refresh
        or sync_info.get("inserted", 0) > 0
        or store.get_meta(META_REBUILT) != "1"
    )
    rebuild_outcomes_from_orders(
        store,
        take_profit_at=take_profit_at,
        stop_loss_pct=stop_loss_pct,
        log_path=LOG_JSON_FILE,
        cutoff_iso=DEFAULT_PROFIT_CUTOFF,
        force=force_rebuild,
    )
    orders = store.list_orders(since=DEFAULT_PROFIT_CUTOFF)
    hints = kind_hints_from_log(LOG_JSON_FILE, orders=orders)
    closed, open_lots = match_trades_and_open_lots(
        orders,
        take_profit_at=take_profit_at,
        stop_loss_pct=stop_loss_pct,
        kind_hints=hints,
    )
    board = build_outcome_board(closed, open_lots=open_lots)
    board["sync"] = sync_info

    with _history_lock:
        _history_cache["ts"] = time.time()
        _history_cache["data"] = board
        return board


def _validate_stocks_traded_list(stocks):
    if not isinstance(stocks, list) or not stocks:
        raise ValueError("stocks_traded_list must be a non-empty list")
    required_keys = ("stockCode", "operationCode", "tradedQuantity")
    for index, stock in enumerate(stocks):
        if not isinstance(stock, dict):
            raise ValueError(f"stocks_traded_list[{index}] must be an object")
        missing = [key for key in required_keys if key not in stock]
        if missing:
            raise ValueError(
                f"stocks_traded_list[{index}] missing fields: {', '.join(missing)}"
            )
    return stocks


def _dashboard_config(settings):
    config = settings_to_dashboard_dict(settings)
    config["MAIN_STRATEGY"] = settings.strategy.main
    config["FALLBACK_ACTIVATED"] = settings.strategy.fallback_enabled
    config["ACCEPTABLE_LOSS_PERCENTAGE"] = settings.risk.acceptable_loss_pct
    config["STOP_LOSS_PERCENTAGE"] = settings.risk.stop_loss_pct
    config["TEMPO_ENTRE_TRADES"] = settings.timing.tempo_entre_trades
    config["DELAY_ENTRE_ORDENS"] = settings.timing.delay_entre_ordens
    config["CANDLE_PERIOD"] = settings.timing.candle_period
    config["stocks_traded_list"] = [
        {
            "stockCode": a.stock_code,
            "operationCode": a.operation_code,
            "tradedQuantity": a.traded_quantity,
        }
        for a in settings.assets
    ]
    return config


def _bot_process_status() -> dict:
    """Inspect the bot's flock file without competing for the lock itself."""
    lock_file = lock_path_for(DEFAULT_DB_PATH)
    status = {"running": False, "pid": None, "environment": None}
    if not lock_file.exists():
        return status
    try:
        payload = json.loads(lock_file.read_text(encoding="utf-8").strip() or "{}")
    except (json.JSONDecodeError, OSError):
        return status

    pid = payload.get("pid")
    status["environment"] = payload.get("environment")
    if not isinstance(pid, int):
        return status
    status["pid"] = pid

    cmdline_path = Path("/proc") / str(pid) / "cmdline"
    try:
        cmdline = cmdline_path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return status
    status["running"] = "main.py" in cmdline
    return status


def _latest_event(event: str):
    entries = read_structured_logs(limit=1, event=event)
    return entries[0] if entries else None


@routes.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})


@routes.route("/login", methods=["GET", "POST"])
def login():
    if not session_auth_enabled():
        return (
            render_template(
                "login.html",
                error=(
                    "Autenticação por senha não está configurada. Gere um hash com "
                    "`python src/app/hash_password.py` e defina DASHBOARD_PASSWORD_HASH no .env."
                ),
                csrf_token="",
                disabled=True,
            ),
            503,
        )

    target = safe_redirect_target(request.args.get("next"))
    if is_authenticated():
        return redirect(target)

    if request.method == "GET":
        return render_template(
            "login.html", error=None, csrf_token=ensure_csrf_token(), disabled=False
        )

    if not csrf_valid():
        return (
            render_template(
                "login.html",
                error="Sessão expirada. Tente novamente.",
                csrf_token=ensure_csrf_token(),
                disabled=False,
            ),
            400,
        )

    caller = client_key()
    blocked_for = login_blocked_for(caller)
    if blocked_for:
        return (
            render_template(
                "login.html",
                error=f"Muitas tentativas. Aguarde {blocked_for}s.",
                csrf_token=ensure_csrf_token(),
                disabled=False,
            ),
            429,
        )

    if not verify_password(request.form.get("password", "")):
        register_failed_login(caller)
        log_event(
            logging.WARNING,
            "Dashboard login failed",
            event="dashboard_login_failed",
            remote_addr=caller,
        )
        return (
            render_template(
                "login.html",
                error="Senha inválida.",
                csrf_token=ensure_csrf_token(),
                disabled=False,
            ),
            401,
        )

    reset_login_attempts(caller)
    start_session()
    log_event(
        logging.INFO,
        "Dashboard login",
        event="dashboard_login",
        remote_addr=caller,
    )
    return redirect(target)


@routes.route("/logout", methods=["POST"])
def logout():
    end_session()
    return redirect(url_for("routes.login"))


@routes.route("/")
def dashboard():
    settings, _ = load_settings()
    return render_template(
        "tracking.html",
        config=_dashboard_config(settings),
        active_page="tracking",
    )


@routes.route("/profit")
def profit_page():
    settings, _ = load_settings()
    return render_template(
        "profit.html",
        config=_dashboard_config(settings),
        active_page="profit",
    )


@routes.route("/config")
def config_page():
    settings, _ = load_settings()
    return render_template(
        "dashboard.html",
        config=_dashboard_config(settings),
        active_page="config",
    )


@routes.route("/get-config", methods=["GET"])
def get_config():
    try:
        settings, _ = load_settings()
        return jsonify(_dashboard_config(settings))
    except Exception as e:
        return jsonify({"error": f"Erro ao carregar config: {str(e)}"}), 500


@routes.route("/api/portfolio", methods=["GET"])
def get_portfolio():
    try:
        return jsonify(get_portfolio_snapshot())
    except ValueError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        return jsonify({"error": f"Erro ao carregar saldo: {str(e)}"}), 500


@routes.route("/api/profit", methods=["GET"])
def get_profit():
    try:
        force = request.args.get("refresh") in {"1", "true", "yes"}
        return jsonify(get_profit_board(force_refresh=force))
    except ValueError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        return jsonify({"error": f"Erro ao carregar profit: {str(e)}"}), 500


@routes.route("/api/logs", methods=["GET"])
def get_logs():
    try:
        limit = request.args.get("limit", 200)
        entries = read_structured_logs(
            limit=int(limit),
            operation_code=request.args.get("operation_code") or None,
            stock_code=request.args.get("stock_code") or None,
            event=request.args.get("event") or None,
        )
        return jsonify({"logs": entries})
    except ValueError:
        return jsonify({"error": "limit must be an integer"}), 400
    except Exception as e:
        return jsonify({"error": f"Erro ao carregar logs: {str(e)}"}), 500


def _yaml_settings():
    """Settings exactly as written in the YAML, ignoring the .env override.

    `load_settings` lets TRADING_ENV shadow `environment`. The config editor must
    edit the file itself, otherwise opening and saving the form would silently
    rewrite the file's environment with the .env value.
    """
    settings, env = load_settings()
    yaml_env = yaml_environment()
    if yaml_env and yaml_env != settings.environment:
        settings = settings.model_copy(update={"environment": yaml_env})
    return settings, env


def _environment_info(effective: str) -> dict:
    yaml_env = yaml_environment()
    override = environment_override()
    return {
        "effective": effective,
        "yaml": yaml_env,
        "override": override,
        "source": ".env" if override else "trading.yaml",
        "conflict": bool(override and yaml_env and override != yaml_env),
    }


def _config_envelope(settings) -> dict:
    effective = environment_override() or settings.environment
    return {
        "config": settings.model_dump(mode="python"),
        "environment": _environment_info(effective),
    }


def _evaluate_payload(settings, payload):
    """Validate a payload against the full model and classify its impact.

    Returns (candidate, response_dict). `candidate` is None when invalid.
    """
    try:
        candidate = apply_config_payload(settings, payload or {})
    except ValidationError as exc:
        return None, {"valid": False, "errors": validation_field_errors(exc)}
    except (ValueError, TypeError) as exc:
        return None, {"valid": False, "errors": [{"field": "", "message": str(exc)}]}

    hard, soft = classify_settings_delta(settings, candidate)
    return candidate, {
        "valid": True,
        "errors": [],
        "hard": hard,
        "soft": soft,
        "changed": bool(hard or soft),
    }


@routes.route("/api/config/schema", methods=["GET"])
def get_config_schema():
    try:
        return jsonify(config_schema())
    except Exception as e:
        return jsonify({"error": f"Erro ao carregar schema: {str(e)}"}), 500


@routes.route("/api/config", methods=["GET"])
def api_get_config():
    try:
        settings, _ = _yaml_settings()
        return jsonify(_config_envelope(settings))
    except Exception as e:
        return jsonify({"error": f"Erro ao carregar config: {str(e)}"}), 500


@routes.route("/api/config/validate", methods=["POST"])
def api_validate_config():
    """Dry-run: reports field errors and restart impact without writing."""
    try:
        settings, _ = _yaml_settings()
        _, result = _evaluate_payload(settings, request.get_json(silent=True))
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": f"Erro ao validar config: {str(e)}"}), 500


@routes.route("/api/config", methods=["POST"])
def api_save_config():
    try:
        settings, _ = _yaml_settings()
        candidate, result = _evaluate_payload(settings, request.get_json(silent=True))
        if candidate is None:
            return jsonify(result), 400

        save_settings(candidate)
        log_event(
            logging.INFO,
            "Dashboard saved config",
            event="dashboard_config_saved",
            soft=result["soft"],
            hard=result["hard"],
        )
        result["saved"] = True
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": f"Erro ao salvar config: {str(e)}"}), 500


@routes.route("/api/config/history", methods=["GET"])
def api_config_history():
    try:
        return jsonify({"backups": list_config_backups()})
    except Exception as e:
        return jsonify({"error": f"Erro ao listar backups: {str(e)}"}), 500


@routes.route("/api/config/revert", methods=["POST"])
def api_revert_config():
    try:
        payload = request.get_json(silent=True) or {}
        name = str(payload.get("name", "")).strip()
        if not name:
            return jsonify({"error": "Informe o backup a restaurar"}), 400

        settings, _ = _yaml_settings()
        restored = restore_config_backup(name)
        hard, soft = classify_settings_delta(settings, restored)
        log_event(
            logging.WARNING,
            "Dashboard reverted config",
            event="dashboard_config_reverted",
            backup=name,
            soft=soft,
            hard=hard,
        )
        return jsonify({"restored": name, "hard": hard, "soft": soft})
    except ValidationError as e:
        return jsonify({"error": "Backup inválido", "errors": validation_field_errors(e)}), 400
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Erro ao restaurar backup: {str(e)}"}), 500


@routes.route("/api/status", methods=["GET"])
def api_status():
    try:
        settings, env = _yaml_settings()
        envelope = _config_envelope(settings)
        path = env.config_path
        modified_at = None
        if path.exists():
            modified_at = datetime.fromtimestamp(
                path.stat().st_mtime, tz=timezone.utc
            ).isoformat()

        return jsonify(
            {
                "bot": _bot_process_status(),
                "environment": envelope["environment"],
                "config": {"path": str(path), "modified_at": modified_at},
                "events": {
                    "last_reload": _latest_event("config_reloaded"),
                    "last_restart_required": _latest_event("config_requires_restart"),
                },
                "backups": len(list_config_backups()),
            }
        )
    except Exception as e:
        return jsonify({"error": f"Erro ao carregar status: {str(e)}"}), 500


@routes.route("/update-config", methods=["POST"])
def update_config():
    try:
        settings, _ = load_settings()
        new_config = request.json
        if not isinstance(new_config, dict):
            return jsonify({"error": "Payload must be a JSON object"}), 400

        unknown_keys = set(new_config.keys()) - UPDATABLE_DASHBOARD_KEYS
        if unknown_keys:
            return jsonify(
                {"error": f"Unsupported config fields: {', '.join(sorted(unknown_keys))}"}
            ), 400

        if "stocks_traded_list" in new_config:
            new_config["stocks_traded_list"] = _validate_stocks_traded_list(
                new_config["stocks_traded_list"]
            )

        updated = apply_dashboard_update(settings, new_config)
        save_settings(updated)
        return jsonify(
            {
                "message": (
                    "Config salva. Risco, timing, regime, grid e alertas "
                    "valem no próximo ciclo. Troca de par, environment ou "
                    "strategy.main exige restart."
                )
            }
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Erro ao atualizar config: {str(e)}"}), 500
