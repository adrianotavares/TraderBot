from flask import Blueprint, render_template, request, jsonify
import json

routes = Blueprint("routes", __name__)

CONFIG_PATH = "src/app/config.json"

UPDATABLE_KEYS = {
    "MAIN_STRATEGY",
    "FALLBACK_ACTIVATED",
    "ACCEPTABLE_LOSS_PERCENTAGE",
    "STOP_LOSS_PERCENTAGE",
    "TEMPO_ENTRE_TRADES",
    "DELAY_ENTRE_ORDENS",
    "stocks_traded_list",
}


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
    """Renderiza o template do painel, garantindo que ele receba a configuração corretamente"""
    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)
    return render_template("dashboard.html", config=config)


@routes.route("/get-config", methods=["GET"])
def get_config():
    """Retorna o config.json completo para o front-end"""
    try:
        with open(CONFIG_PATH, "r") as f:
            config = json.load(f)
        return jsonify(config)
    except Exception as e:
        return jsonify({"error": f"Erro ao carregar configuração: {str(e)}"}), 500


@routes.route("/update-config", methods=["POST"])
def update_config():
    try:
        with open(CONFIG_PATH, "r") as f:
            existing_config = json.load(f)

        new_config = request.json
        if not isinstance(new_config, dict):
            return jsonify({"error": "Payload must be a JSON object"}), 400

        unknown_keys = set(new_config.keys()) - UPDATABLE_KEYS
        if unknown_keys:
            return jsonify(
                {"error": f"Unsupported config fields: {', '.join(sorted(unknown_keys))}"}
            ), 400

        if "stocks_traded_list" in new_config:
            new_config["stocks_traded_list"] = _validate_stocks_traded_list(
                new_config["stocks_traded_list"]
            )

        for key in UPDATABLE_KEYS:
            if key in new_config:
                existing_config[key] = new_config[key]

        with open(CONFIG_PATH, "w") as f:
            json.dump(existing_config, f, indent=4)

        return jsonify({"message": "Configuração atualizada com sucesso!"})

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Erro ao atualizar configuração: {str(e)}"}), 500
