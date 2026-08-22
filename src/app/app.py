import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from flask import Flask
from routes import routes
from security import (
    assert_flask_bind_allowed,
    enforce_token,
    flask_bind_host,
    flask_token,
)

app = Flask(__name__)
app.register_blueprint(routes)
app.before_request(enforce_token)


@app.context_processor
def inject_flask_token():
    return {"flask_token": flask_token()}


if __name__ == "__main__":
    host = flask_bind_host()
    port = int(os.getenv("FLASK_PORT", "5000"))
    assert_flask_bind_allowed(host, flask_token())
    app.run(debug=False, host=host, port=port)
