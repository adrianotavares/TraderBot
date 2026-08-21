import os
import sys
import threading
import time

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from flask import Blueprint, render_template, request, jsonify

from config.settings import (
    UPDATABLE_DASHBOARD_KEYS,
    apply_dashboard_update,
    load_settings,
    save_settings,
    settings_to_dashboard_dict,
)
from modules.BinanceClient import BinanceClient
from modules.logging_setup import read_structured_logs
from persistence.state_store import StateStore
from services.portfolio import fetch_portfolio

routes = Blueprint("routes", __name__)

_PORTFOLIO_CACHE_TTL = 5.0
_portfolio_lock = threading.Lock()
_portfolio_cache = {"ts": 0.0, "data": None}
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


@routes.route("/")
def dashboard():
    settings, _ = load_settings()
    return render_template(
        "acompanhamento.html",
        config=_dashboard_config(settings),
        active_page="acompanhamento",
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
        return jsonify({"error": f"Erro ao carregar configuração: {str(e)}"}), 500


@routes.route("/api/portfolio", methods=["GET"])
def get_portfolio():
    try:
        return jsonify(get_portfolio_snapshot())
    except ValueError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        return jsonify({"error": f"Erro ao carregar saldo: {str(e)}"}), 500


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
        return jsonify({"message": "Configuração atualizada com sucesso! Reinicie o bot para aplicar."})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Erro ao atualizar configuração: {str(e)}"}), 500
