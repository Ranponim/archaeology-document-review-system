import subprocess
from pathlib import Path

import yaml
import pytest


@pytest.fixture
def compose():
    with Path("compose.yml").open(encoding="utf-8") as compose_file:
        return yaml.safe_load(compose_file)


def test_compose_declares_required_services_and_volumes(compose):
    assert set(compose["services"]) == {"web", "worker", "neo4j", "redis"}
    assert compose["services"]["web"]["ports"] == ["8080:8080"]
    assert {"review_data", "neo4j_data"} <= set(compose["volumes"])


def test_env_file_is_gitignored():
    result = subprocess.run(["git", "check-ignore", "-q", ".env"], check=False)

    assert result.returncode == 0
