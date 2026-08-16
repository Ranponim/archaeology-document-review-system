import subprocess
from pathlib import Path

import pytest
import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def compose():
    with (REPOSITORY_ROOT / "compose.yml").open(encoding="utf-8") as compose_file:
        return yaml.safe_load(compose_file)


def test_compose_declares_required_services_and_volumes(compose):
    assert set(compose["services"]) == {"web", "worker", "neo4j", "redis"}
    assert compose["services"]["web"]["ports"] == ["${WEB_PORT:-8080}:8080"]
    assert {"review_data", "neo4j_data"} <= set(compose["volumes"])


def test_worker_receives_the_same_neo4j_credentials_as_the_database(compose):
    worker_environment = compose["services"]["worker"]["environment"]

    assert worker_environment["NEO4J_USER"] == "neo4j"
    assert worker_environment["NEO4J_PASSWORD"] == "${NEO4J_PASSWORD}"


def test_web_and_worker_receive_the_unified_openrouter_api_key(compose):
    web = compose["services"]["web"]
    worker = compose["services"]["worker"]

    assert web["environment"]["OPENROUTER_API_KEY"] == "${OPENROUTER_API_KEY}"
    assert worker["environment"]["OPENROUTER_API_KEY"] == "${OPENROUTER_API_KEY}"
    assert "AI_API_KEY" not in web["environment"]
    assert "AI_API_KEY" not in worker["environment"]


def test_web_service_runs_fastapi_on_the_local_web_port(compose):
    web = compose["services"]["web"]

    assert web["build"] == {
        "context": ".",
        "dockerfile": "backend/Dockerfile",
    }
    assert web["command"] == [
        "uvicorn",
        "app.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        "8080",
    ]
    assert web["ports"] == ["${WEB_PORT:-8080}:8080"]
    assert web["environment"]["REDIS_URL"] == "redis://redis:6379/0"
    assert web["environment"]["NEO4J_URI"] == "bolt://neo4j:7687"
    assert "AI_API_KEY" not in web["environment"]
    assert web["environment"]["OPENROUTER_API_KEY"] == "${OPENROUTER_API_KEY}"


def test_worker_uses_the_same_frontend_capable_application_build(compose):
    assert compose["services"]["worker"]["build"] == {
        "context": ".",
        "dockerfile": "backend/Dockerfile",
    }


def test_env_file_is_gitignored():
    result = subprocess.run(
        ["git", "check-ignore", "-q", ".env"],
        cwd=REPOSITORY_ROOT,
        check=False,
    )

    assert result.returncode == 0
