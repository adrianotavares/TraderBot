import os
import sys

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

routes = Blueprint("routes", __name__)


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


@routes.route("/")
def dashboard():
    settings, _ = load_settings()
    config = settings_to_dashboard_dict(settings)
    config["MAIN_STRATEGY"] = settings.strategy.main
    config["FALLBACK_ACTIVATED"] = settings.strategy.fallback_enabled
    config["ACCEPTABLE_LOSS_PERCENTAGE"] = settings.risk.acceptable_loss_pct
    config["STOP_LOSS_PERCENTAGE"] = settings.risk.stop_loss_pct
    config["TEMPO_ENTRE_TRADES"] = settings.timing.tempo_entre_trades
    config["DELAY_ENTRE_ORDENS"] = settings.timing.delay_entre_ordens
    config["stocks_traded_list"] = [
        {
            "stockCode": a.stock_code,
            "operationCode": a.operation_code,
            "tradedQuantity": a.traded_quantity,
        }
        for a in settings.assets
    ]
    return render_template("dashboard.html", config=config)


@routes.route("/get-config", methods=["GET"])
def get_config():
    try:
        settings, _ = load_settings()
        config = settings_to_dashboard_dict(settings)
        config["MAIN_STRATEGY"] = settings.strategy.main
        config["FALLBACK_ACTIVATED"] = settings.strategy.fallback_enabled
        config["ACCEPTABLE_LOSS_PERCENTAGE"] = settings.risk.acceptable_loss_pct
        config["STOP_LOSS_PERCENTAGE"] = settings.risk.stop_loss_pct
        config["TEMPO_ENTRE_TRADES"] = settings.timing.tempo_entre_trades
        config["DELAY_ENTRE_ORDENS"] = settings.timing.delay_entre_ordens
        config["stocks_traded_list"] = [
            {
                "stockCode": a.stock_code,
                "operationCode": a.operation_code,
                "tradedQuantity": a.traded_quantity,
            }
            for a in settings.assets
        ]
        return jsonify(config)
    except Exception as e:
        return jsonify({"error": f"Erro ao carregar configuração: {str(e)}"}), 500


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
