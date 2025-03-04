import sys
import os

# Obtém o caminho correto do diretório `src`
SRC_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

from flask import Flask
from routes import routes

app = Flask(__name__)
app.register_blueprint(routes)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
