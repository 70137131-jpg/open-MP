"""HTTP-level tests for the Flask surface."""

from __future__ import annotations

import json

from backend import create_app
from backend.config import Config

from .conftest import requires_gcc


def test_index_serves_the_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"<title>" in response.data


def test_health_reports_toolchain_and_limits(client, config):
    payload = client.get("/health").get_json()
    assert payload["status"] in {"ok", "degraded"}
    assert set(payload["toolchain"]) == {"gcc", "g++", "mpicc", "mpicxx", "mpirun"}
    assert payload["limits"]["maxWorkers"] == config.max_workers


def test_health_is_cached(app):
    app.config["OPENMP"] = Config(
        workdir=app.config["OPENMP"].workdir, health_cache_seconds=300
    )
    client = app.test_client()
    first = client.get("/health").get_json()
    with app.app_context():
        pass
    second = client.get("/health").get_json()
    assert first == second
    assert app.extensions["openmp_health_cache"]["payload"] is not None


def test_examples_endpoint_returns_the_catalogue(client):
    payload = client.get("/examples").get_json()
    examples = payload["examples"]
    assert len(examples) >= 5
    first = examples[0]
    assert set(first) == {"id", "title", "language", "mode", "description", "source"}
    assert "#include" in first["source"]


def test_compile_rejects_non_json_body(client):
    response = client.post("/compile", data="not json", content_type="text/plain")
    assert response.status_code == 400
    assert response.get_json()["success"] is False


def test_compile_rejects_missing_code(client):
    response = client.post("/compile", json={"language": "c"})
    assert response.status_code == 400
    assert "No code" in response.get_json()["stderr"]


def test_compile_rejects_bad_language(client):
    response = client.post("/compile", json={"code": "int main(){}", "language": "go"})
    assert response.status_code == 400


def test_oversized_body_is_refused(client, config):
    response = client.post("/compile", json={"code": "x" * (config.max_code_bytes + 1)})
    assert response.status_code == 413


@requires_gcc
def test_compile_happy_path(client):
    code = '#include <stdio.h>\nint main(void){ printf("ok\\n"); return 0; }'
    payload = client.post("/compile", json={"code": code, "threads": 2}).get_json()
    assert payload["success"] is True
    assert payload["output"].strip() == "ok"
    assert payload["workers"] == 2
    assert payload["compiler"] == "gcc"
    assert "compileMs" in payload and "runMs" in payload


@requires_gcc
def test_compile_error_response_shape(client):
    payload = client.post("/compile", json={"code": "int main(void) { oops }"}).get_json()
    assert payload["success"] is False
    assert payload["stage"] == "compile"
    assert payload["error"] == "Compilation error"


def test_rate_limit_returns_429(workdir):
    app = create_app(
        Config(workdir=workdir, rate_limit_requests=2, rate_limit_window_seconds=60)
    )
    client = app.test_client()
    body = {"code": ""}  # invalid on purpose: the limiter runs before validation
    assert client.post("/compile", json=body).status_code == 400
    assert client.post("/compile", json=body).status_code == 400
    response = client.post("/compile", json=body)
    assert response.status_code == 429
    assert response.headers["Retry-After"]


def test_rate_limit_is_per_client(workdir):
    app = create_app(
        Config(workdir=workdir, rate_limit_requests=1, rate_limit_window_seconds=60)
    )
    client = app.test_client()
    headers_a = {"X-Forwarded-For": "10.0.0.1"}
    headers_b = {"X-Forwarded-For": "10.0.0.2"}
    assert client.post("/compile", json={"code": ""}, headers=headers_a).status_code == 400
    assert client.post("/compile", json={"code": ""}, headers=headers_a).status_code == 429
    assert client.post("/compile", json={"code": ""}, headers=headers_b).status_code == 400


def test_unknown_route_returns_json_404(client):
    response = client.get("/does-not-exist")
    assert response.status_code == 404
    assert response.get_json()["error"] == "Not found"


def test_wrong_method_returns_json_405(client):
    response = client.get("/compile")
    assert response.status_code == 405
    assert response.get_json()["error"] == "Method not allowed"


def test_cors_header_is_present(client):
    response = client.get("/health", headers={"Origin": "https://example.com"})
    assert response.headers.get("Access-Control-Allow-Origin")


def test_static_assets_are_served(client):
    for path in ("/static/css/styles.css", "/static/js/app.js", "/static/js/examples.data.js"):
        assert client.get(path).status_code == 200, path


def test_response_is_valid_json_for_every_endpoint(client):
    for path in ("/health", "/examples"):
        json.loads(client.get(path).data)
