from flask import Blueprint, render_template, request, jsonify
import json

routes = Blueprint("routes", __name__)

CONFIG_PATH = "src/app/config.json"


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
        # Carregar o config.json existente
        with open(CONFIG_PATH, "r") as f:
            existing_config = json.load(f)

        # Obter os novos valores do formulário
        new_config = request.json

        # Atualizar apenas os campos enviados, mantendo os demais inalterados
        existing_config.update(new_config)

        # Salvar o novo arquivo config.json
        with open(CONFIG_PATH, "w") as f:
            json.dump(existing_config, f, indent=4)

        return jsonify({"message": "Configuração atualizada com sucesso!"})

    except Exception as e:
        return jsonify({"error": f"Erro ao atualizar configuração: {str(e)}"}), 500
