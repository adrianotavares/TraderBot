import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

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
from services.chart_data import (
    DEFAULT_BARS,
    MAX_BARS,
    MIN_BARS,
    WARMUP_CANDLES,
    build_aggregate_chart_payload,
    build_chart_payload,
)
from services.market_data import MarketDataService
from services.order_sync import DEFAULT_PROFIT_CUTOFF, sync_filled_orders_from_binance
from services.outcome_history import (
    META_REBUILT,
    build_outcome_board,
    kind_hints_from_log,
    match_trades_and_open_lots,
    rebuild_outcomes_from_orders,
    reconcile_open_lots,
)
from services.portfolio import fetch_portfolio
from services.portfolio_actions import (
    PortfolioActionError,
    execute_liquidate,
    execute_rebalance,
    preview_liquidate,
    preview_rebalance,
)
from services.regime_detector import RegimeDetector

routes = Blueprint("routes", __name__)

_PORTFOLIO_CACHE_TTL = 5.0
_HISTORY_CACHE_TTL = 30.0
# Charts poll far slower than the log feed: a 4h candle barely moves in a minute,
# and refetching klines for every asset competes with the bot's own rate limit.
_CHART_CACHE_TTL = 60.0
_CHART_CACHE_MAX_ENTRIES = 8
_portfolio_lock = threading.Lock()
_portfolio_cache = {"ts": 0.0, "data": None}
_portfolio_action_lock = threading.Lock()
_history_lock = threading.Lock()
_history_cache = {"ts": 0.0, "data": None}
_chart_lock = threading.Lock()
_chart_cache: dict = {}
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


def _invalidate_portfolio_cache() -> None:
    with _portfolio_lock:
        _portfolio_cache["data"] = None
        _portfolio_cache["ts"] = 0.0


def _spot_client_for_settings():
    settings, env = load_settings()
    if not env.api_key or not env.secret_key:
        raise ValueError("Credenciais da Binance não configuradas")
    client = get_spot_client(
        env.api_key,
        env.secret_key,
        testnet=settings.environment == "testnet",
    )
    return settings, client


def _live_portfolio_snapshot(force_refresh: bool = False):
    """Same snapshot as Tracking. None when Binance/credentials are unavailable."""
    if force_refresh:
        _invalidate_portfolio_cache()
    try:
        return get_portfolio_snapshot()
    except Exception:
        return None


def _overlay_profit_nav(board: dict, snapshot: Optional[dict]) -> None:
    if snapshot and snapshot.get("total_usd") is not None:
        board["nav_usd"] = round(float(snapshot["total_usd"]), 2)


def get_profit_board(force_refresh: bool = False):
    now = time.time()
    cached_board = None
    with _history_lock:
        cached = _history_cache["data"]
        if (
            not force_refresh
            and cached is not None
            and now - _history_cache["ts"] < _HISTORY_CACHE_TTL
        ):
            cached_board = cached

    if cached_board is not None:
        _overlay_profit_nav(cached_board, _live_portfolio_snapshot())
        return cached_board

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
    snapshot = _live_portfolio_snapshot(force_refresh=force_refresh)
    warnings = []
    if snapshot:
        open_lots, warnings = reconcile_open_lots(
            open_lots, snapshot.get("assets") or []
        )
    else:
        warnings.append(
            {
                "code": "nav_unavailable",
                "operation_code": "",
                "stock_code": "",
                "message": (
                    "Saldo live da Binance indisponível; "
                    "posição aberta ficou só no FIFO."
                ),
            }
        )
    nav_usd = None if not snapshot else snapshot.get("total_usd")
    board = build_outcome_board(
        closed,
        open_lots=open_lots,
        nav_usd=nav_usd,
        warnings=warnings,
    )
    board["sync"] = sync_info

    with _history_lock:
        _history_cache["ts"] = time.time()
        _history_cache["data"] = board
        return board


def _chart_position(state, holding: Optional[dict]) -> dict:
    """Position as the chart should show it.

    `actual_trade_position` is the bot's own verdict (balance >= step_size), so
    dust left behind by a sell does not resurrect the take profit / stop loss
    lines. Price and P&L come from the live portfolio when it is available.
    """
    holding = holding or {}
    return {
        "open": bool(state.actual_trade_position),
        "quantity": float(holding.get("quantity") or 0),
        "entry_price": float(state.last_buy_price or 0),
        "peak_price": float(getattr(state, "stop_loss_peak_price", 0) or 0),
        "last_price": float(holding.get("price") or 0),
        "pnl_usd": holding.get("pnl_usd"),
        "pnl_pct": holding.get("pnl_pct"),
    }


def _empty_chart(asset, error: str) -> dict:
    return {
        "stock_code": asset.stock_code,
        "operation_code": asset.operation_code,
        "candles": [],
        "regime": [],
        "current_regime": None,
        "trailing_stop": [],
        "position": {},
        "levels": None,
        "markers": [],
        "error": error,
    }


def _chart_holdings() -> tuple[dict, dict]:
    try:
        snapshot = get_portfolio_snapshot()
    except Exception:
        logging.warning("Building charts without portfolio data", exc_info=True)
        return {}, {}
    return {
        holding["operation_code"]: holding for holding in snapshot.get("assets", [])
    }, {
        "total_pnl_usd": snapshot.get("total_pnl_usd"),
        "total_pnl_pct": snapshot.get("total_pnl_pct"),
    }


def get_tracking_charts(
    operation_code: Optional[str] = None,
    bars: int = DEFAULT_BARS,
) -> dict:
    key = (operation_code or "", int(bars))
    now = time.time()
    with _chart_lock:
        cached = _chart_cache.get(key)
        if cached is not None and now - cached["ts"] < _CHART_CACHE_TTL:
            return cached["data"]

    settings, env = load_settings()
    if not env.api_key or not env.secret_key:
        raise ValueError("Credenciais da Binance não configuradas")

    assets = list(settings.assets)
    if operation_code:
        assets = [a for a in assets if a.operation_code == operation_code]
        if not assets:
            raise LookupError(f"Ativo não configurado: {operation_code}")

    client = get_spot_client(
        env.api_key,
        env.secret_key,
        testnet=settings.environment == "testnet",
    )
    store = StateStore()
    candle_period = settings.timing.candle_period
    holdings, portfolio_totals = _chart_holdings()

    if not operation_code:
        klines_by_symbol: dict = {}
        states = {}
        limit = min(1000, int(bars))
        for asset in assets:
            try:
                market = MarketDataService(client, asset.operation_code, candle_period)
                klines_by_symbol[asset.operation_code] = market.fetch_klines(limit=limit)
                states[asset.operation_code] = store.load_state(asset.operation_code)
            except Exception as exc:
                logging.exception(
                    "Aggregate chart skipped klines for %s", asset.operation_code
                )
                states[asset.operation_code] = store.load_state(asset.operation_code)

        aggregate = build_aggregate_chart_payload(
            klines_by_symbol,
            holdings=holdings,
            states=states,
            configured_codes=[asset.operation_code for asset in assets],
            risk=settings.risk,
            bars=int(bars),
            total_pnl_usd=portfolio_totals.get("total_pnl_usd"),
            total_pnl_pct=portfolio_totals.get("total_pnl_pct"),
        )
        data = {
            "candle_period": candle_period,
            "strategy": settings.strategy.main,
            "regime_enabled": settings.regime.enabled,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "assets": [],
            "aggregate": aggregate,
        }
        with _chart_lock:
            if len(_chart_cache) >= _CHART_CACHE_MAX_ENTRIES:
                _chart_cache.clear()
            _chart_cache[key] = {"ts": time.time(), "data": data}
        return data

    detector = RegimeDetector(**settings.regime.model_dump())
    orders = store.list_orders(since=DEFAULT_PROFIT_CUTOFF)
    limit = min(1000, int(bars) + WARMUP_CANDLES)

    charts = []
    for asset in assets:
        try:
            market = MarketDataService(client, asset.operation_code, candle_period)
            state = store.load_state(asset.operation_code)
            charts.append(
                build_chart_payload(
                    market.fetch_klines(limit=limit),
                    stock_code=asset.stock_code,
                    operation_code=asset.operation_code,
                    candle_period=candle_period,
                    risk=settings.risk,
                    position=_chart_position(state, holdings.get(asset.operation_code)),
                    take_profit_index=state.take_profit_index,
                    detector=detector,
                    store=store,
                    orders=orders,
                    strategy_main=settings.strategy.main,
                    strategy_args=settings.strategy.main_args,
                    bars=int(bars),
                )
            )
        except Exception as exc:
            # One failing symbol must not blank the whole page.
            logging.exception("Chart payload failed for %s", asset.operation_code)
            charts.append(_empty_chart(asset, str(exc)))

    data = {
        "candle_period": candle_period,
        "strategy": settings.strategy.main,
        "regime_enabled": settings.regime.enabled,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "assets": charts,
        "aggregate": None,
    }
    with _chart_lock:
        if len(_chart_cache) >= _CHART_CACHE_MAX_ENTRIES:
            _chart_cache.clear()
        _chart_cache[key] = {"ts": time.time(), "data": data}
    return data


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


@routes.route("/balance")
def balance_page():
    settings, _ = load_settings()
    return render_template(
        "balance.html",
        config=_dashboard_config(settings),
        active_page="balance",
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


def _action_busy_response():
    return jsonify({"error": "Já existe uma ação de portfólio em andamento"}), 409


def _portfolio_action_error_response(exc: PortfolioActionError):
    return jsonify({"error": str(exc), "blockers": exc.blockers}), 400


@routes.route("/api/portfolio/hold", methods=["GET"])
def api_portfolio_hold_status():
    store = StateStore()
    return jsonify({"hold": store.is_action_hold()})


@routes.route("/api/portfolio/hold", methods=["POST"])
def api_portfolio_hold():
    payload = request.get_json(silent=True) or {}
    if payload.get("hold") is not False:
        return jsonify({"error": "Use hold=false para liberar o pause de ciclos"}), 400
    store = StateStore()
    store.set_action_hold(False)
    log_event(
        logging.WARNING,
        "Dashboard cleared portfolio action hold",
        event="portfolio_hold_cleared",
    )
    return jsonify({"hold": False})


@routes.route("/api/cycles/control", methods=["GET"])
def api_cycles_control_status():
    store = StateStore()
    return jsonify(
        {
            "operator_hold": store.is_operator_hold(),
            "action_hold": store.is_action_hold(),
        }
    )


@routes.route("/api/cycles/control", methods=["POST"])
def api_cycles_control():
    payload = request.get_json(silent=True) or {}
    if payload.get("hold") not in (True, False):
        return jsonify(
            {
                "error": "Use hold=true para pausar entradas ou hold=false para retomar"
            }
        ), 400
    store = StateStore()
    held = bool(payload["hold"])
    store.set_operator_hold(held)
    log_event(
        logging.WARNING,
        "Dashboard set operator hold" if held else "Dashboard cleared operator hold",
        event="operator_hold_set" if held else "operator_hold_cleared",
        hold=held,
    )
    return jsonify(
        {
            "operator_hold": store.is_operator_hold(),
            "action_hold": store.is_action_hold(),
        }
    )


@routes.route("/api/portfolio/rebalance/preview", methods=["POST"])
def api_rebalance_preview():
    payload = request.get_json(silent=True) or {}
    try:
        settings, client = _spot_client_for_settings()
        result = preview_rebalance(client, settings.assets, payload.get("weights"))
        result["environment"] = settings.environment
        return jsonify(result)
    except PortfolioActionError as exc:
        return _portfolio_action_error_response(exc)
    except ValueError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        return jsonify({"error": f"Erro ao pré-visualizar Balance: {str(e)}"}), 500


@routes.route("/api/portfolio/rebalance", methods=["POST"])
def api_rebalance_execute():
    payload = request.get_json(silent=True) or {}
    if not _portfolio_action_lock.acquire(blocking=False):
        return _action_busy_response()
    try:
        settings, client = _spot_client_for_settings()
        store = StateStore()
        result = execute_rebalance(
            client,
            settings.assets,
            payload.get("weights"),
            store,
            payload.get("confirm", ""),
        )
        result["environment"] = settings.environment
        _invalidate_portfolio_cache()
        status = 200 if result.get("ok") else 207
        return jsonify(result), status
    except PortfolioActionError as exc:
        return _portfolio_action_error_response(exc)
    except ValueError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        return jsonify({"error": f"Erro ao executar Balance: {str(e)}"}), 500
    finally:
        _portfolio_action_lock.release()


@routes.route("/api/portfolio/liquidate/preview", methods=["POST"])
def api_liquidate_preview():
    payload = request.get_json(silent=True) or {}
    try:
        settings, client = _spot_client_for_settings()
        result = preview_liquidate(client, settings.assets, payload.get("symbols"))
        result["environment"] = settings.environment
        return jsonify(result)
    except PortfolioActionError as exc:
        return _portfolio_action_error_response(exc)
    except ValueError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        return jsonify({"error": f"Erro ao pré-visualizar Liquidate: {str(e)}"}), 500


@routes.route("/api/portfolio/liquidate", methods=["POST"])
def api_liquidate_execute():
    payload = request.get_json(silent=True) or {}
    if not _portfolio_action_lock.acquire(blocking=False):
        return _action_busy_response()
    try:
        settings, client = _spot_client_for_settings()
        store = StateStore()
        result = execute_liquidate(
            client,
            settings.assets,
            payload.get("symbols"),
            store,
            payload.get("confirm", ""),
        )
        result["environment"] = settings.environment
        _invalidate_portfolio_cache()
        status = 200 if result.get("ok") else 207
        return jsonify(result), status
    except PortfolioActionError as exc:
        return _portfolio_action_error_response(exc)
    except ValueError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        return jsonify({"error": f"Erro ao executar Liquidate: {str(e)}"}), 500
    finally:
        _portfolio_action_lock.release()


@routes.route("/api/profit", methods=["GET"])
def get_profit():
    try:
        force = request.args.get("refresh") in {"1", "true", "yes"}
        return jsonify(get_profit_board(force_refresh=force))
    except ValueError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        return jsonify({"error": f"Erro ao carregar profit: {str(e)}"}), 500


@routes.route("/api/tracking/charts", methods=["GET"])
def api_tracking_charts():
    try:
        bars = max(MIN_BARS, min(int(request.args.get("bars", DEFAULT_BARS)), MAX_BARS))
    except (TypeError, ValueError):
        return jsonify({"error": "bars must be an integer"}), 400
    try:
        return jsonify(
            get_tracking_charts(request.args.get("operation_code") or None, bars)
        )
    except LookupError as e:
        return jsonify({"error": str(e)}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        return jsonify({"error": f"Erro ao carregar gráficos: {str(e)}"}), 500


@routes.route("/api/logs", methods=["GET"])
def get_logs():
    try:
        limit = request.args.get("limit", 200)
        requested = request.args.get("operation_code") or None
        allowed = _configured_operation_codes()
        if requested and allowed is not None and requested not in allowed:
            return jsonify({"logs": []})
        entries = read_structured_logs(
            limit=int(limit),
            operation_code=requested,
            operation_codes=None if requested else allowed,
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


def _configured_operation_codes(settings=None) -> set[str] | None:
    """Pairs currently loaded from YAML. None means the filter could not be built."""
    try:
        if settings is None:
            settings, _ = _yaml_settings()
        return {asset.operation_code for asset in settings.assets}
    except Exception:
        logging.exception("Failed to load configured assets")
        return None


def _cycle_heartbeats_payload(settings=None) -> list[dict]:
    """Read-only countdown source. A store failure must not break /api/status."""
    try:
        rows = StateStore().list_cycle_heartbeats()
    except Exception:
        logging.exception("Failed to load cycle heartbeats")
        return []
    allowed = _configured_operation_codes(settings)
    payload = []
    for row in rows:
        code = row.get("operation_code")
        if allowed is not None and code not in allowed:
            continue
        payload.append(
            {
                "operation_code": code,
                "phase": row.get("phase"),
                "cycle_started_at": row.get("cycle_started_at"),
                "cycle_finished_at": row.get("cycle_finished_at"),
                "sleep_seconds": row.get("sleep_seconds"),
                "next_cycle_at": row.get("next_cycle_at"),
                "sleep_reason": row.get("sleep_reason"),
                "updated_at": row.get("updated_at"),
            }
        )
    return payload


def _hold_flags() -> dict:
    try:
        store = StateStore()
        return {
            "operator_hold": store.is_operator_hold(),
            "action_hold": store.is_action_hold(),
        }
    except Exception:
        logging.exception("Failed to load hold flags")
        return {"operator_hold": False, "action_hold": False}


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
                "server_time": datetime.now(timezone.utc).isoformat(),
                "cycles": _cycle_heartbeats_payload(settings),
                **_hold_flags(),
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
