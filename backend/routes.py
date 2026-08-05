"""HTTP surface: static frontend, health, example catalogue and /compile."""

from __future__ import annotations

import logging
import time

from flask import Blueprint, current_app, jsonify, request, send_from_directory

from .config import Config
from .examples import catalogue
from .executor import JobError, JobRequest, cleanup_stale_jobs, run_job, toolchain_status
from .ratelimit import ConcurrencyGate, RateLimiter

logger = logging.getLogger(__name__)

bp = Blueprint("api", __name__)

# How long a request waits for a free compile slot before giving up.
QUEUE_WAIT_SECONDS = 5.0


def _config() -> Config:
    return current_app.config["OPENMP"]


def _limiter() -> RateLimiter:
    return current_app.extensions["openmp_limiter"]


def _gate() -> ConcurrencyGate:
    return current_app.extensions["openmp_gate"]


def _client_key() -> str:
    """Best-effort client identity, honouring one proxy hop."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


@bp.get("/")
def index():
    # index.html stays at the project root so the page can also be served as a
    # plain static file (Vercel, nginx) with the API on another origin.
    return send_from_directory(current_app.config["SITE_ROOT"], "index.html")


@bp.get("/favicon.ico")
def favicon():
    return ("", 204)


@bp.get("/health")
def health():
    """Toolchain report. Cached, since the frontend polls it."""
    config = _config()
    cache = current_app.extensions["openmp_health_cache"]
    now = time.monotonic()
    if cache["payload"] is None or now - cache["at"] > config.health_cache_seconds:
        cache["payload"] = toolchain_status(config)
        cache["at"] = now
    return jsonify(cache["payload"])


@bp.get("/examples")
def examples():
    return jsonify({"examples": catalogue()})


@bp.post("/compile")
def compile_and_run():
    config = _config()

    allowed, retry_after = _limiter().check(_client_key())
    if not allowed:
        response = jsonify(
            {
                "success": False,
                "error": "Rate limit exceeded",
                "stderr": (
                    f"This service allows {config.rate_limit_requests} runs per "
                    f"{config.rate_limit_window_seconds}s. Try again in {retry_after}s."
                ),
            }
        )
        response.status_code = 429
        response.headers["Retry-After"] = str(retry_after)
        return response

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(JobError("Invalid request", "Expected a JSON object body.").to_dict()), 400

    try:
        job = JobRequest.parse(payload, config)
    except JobError as exc:
        return jsonify(exc.to_dict()), exc.status

    with _gate().slot(timeout=QUEUE_WAIT_SECONDS) as acquired:
        if not acquired:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Server busy",
                        "stderr": "Too many programs are running right now. Try again shortly.",
                    }
                ),
                503,
            )
        try:
            result = run_job(job, config)
        except JobError as exc:
            return jsonify(exc.to_dict()), exc.status
        except Exception:  # pragma: no cover - defensive
            logger.exception("compile job failed unexpectedly")
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Internal server error",
                        "stderr": "The compiler service hit an unexpected error.",
                    }
                ),
                500,
            )

    logger.info(
        "job mode=%s lang=%s workers=%d stage=%s success=%s compile=%dms run=%dms",
        job.mode.value,
        job.language.value,
        job.workers,
        result.stage,
        result.success,
        result.compile_ms,
        result.run_ms,
    )
    cleanup_stale_jobs(config)
    return jsonify(result.to_dict())
