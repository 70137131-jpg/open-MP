"""Application factory for the OpenMP/MPI online compiler."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from flask import Flask, jsonify
from flask_cors import CORS

from .config import Config
from .ratelimit import ConcurrencyGate, RateLimiter

PROJECT_ROOT = Path(__file__).resolve().parent.parent

__all__ = ["create_app", "Config", "PROJECT_ROOT"]


def _configure_logging() -> None:
    level = os.environ.get("OPENMP_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )


def create_app(config: Config | None = None) -> Flask:
    """Build the Flask app. Tests call this directly with a custom config."""
    _configure_logging()
    config = config or Config.from_env()

    app = Flask(
        __name__,
        static_folder=str(PROJECT_ROOT / "static"),
        static_url_path="/static",
    )
    app.config["OPENMP"] = config
    app.config["SITE_ROOT"] = str(PROJECT_ROOT)
    app.config["MAX_CONTENT_LENGTH"] = config.max_code_bytes + 8 * 1024
    app.config["JSON_SORT_KEYS"] = False

    CORS(app, resources={r"/*": {"origins": config.cors_origins}})

    app.extensions["openmp_limiter"] = RateLimiter(
        config.rate_limit_requests, config.rate_limit_window_seconds
    )
    app.extensions["openmp_gate"] = ConcurrencyGate(config.max_concurrent_jobs)
    app.extensions["openmp_health_cache"] = {"payload": None, "at": 0.0}

    config.workdir.mkdir(parents=True, exist_ok=True)

    from .routes import bp  # imported late so the blueprint sees a built app

    app.register_blueprint(bp)

    @app.errorhandler(404)
    def not_found(_error):
        return jsonify({"success": False, "error": "Not found"}), 404

    @app.errorhandler(405)
    def method_not_allowed(_error):
        return jsonify({"success": False, "error": "Method not allowed"}), 405

    @app.errorhandler(413)
    def payload_too_large(_error):
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Payload too large",
                    "stderr": f"Request body exceeds {config.max_code_bytes // 1024} KB.",
                }
            ),
            413,
        )

    return app
