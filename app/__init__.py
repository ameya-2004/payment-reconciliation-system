import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def create_app(data_dir=None):
    """Small read-only API over a dataset folder. Run `python run_workflow.py` first so the outputs exist."""
    from flask import Flask

    app = Flask(__name__)
    app.config["DATA_DIR"] = str(data_dir or os.getenv("RECON_DATA_DIR") or ROOT / "data" / "starter")

    from app.routes.dashboard import dashboard_bp
    app.register_blueprint(dashboard_bp)
    return app
