import json
import os
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pytest

RUN_COMPOSE_INTEGRATION = os.environ.get("RUN_COMPOSE_INTEGRATION") == "1"
PROJECT_NAME = "archaeology-task5-smoke"
BASE_URL = "http://127.0.0.1:18080"
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _compose(environment, *arguments, check=True):
    return subprocess.run(
        ["docker", "compose", "-p", PROJECT_NAME, *arguments],
        cwd=REPOSITORY_ROOT,
        env=environment,
        check=check,
        capture_output=True,
        text=True,
    )


def _json_request(method, path, payload=None):
    body = None if payload is None else json.dumps(payload).encode()
    request = Request(
        BASE_URL + path,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        return error.code, json.loads(error.read())


def _upload(project_id):
    boundary = "task5-smoke-boundary"
    body = (
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="sample.pdf"\r\n'
            "Content-Type: application/pdf\r\n\r\n"
        ).encode()
        + b"%PDF\r\ninvalid-for-conversion\r\n"
        + f"\r\n--{boundary}--\r\n".encode()
    )
    request = Request(
        f"{BASE_URL}/api/projects/{project_id}/documents?stage=source",
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        return error.code, json.loads(error.read())


def _wait_for_project_api():
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            status, body = _json_request(
                "POST", "/api/projects", {"name": "compose-smoke"}
            )
        except (OSError, URLError, TimeoutError):
            time.sleep(1)
            continue
        if status == 201:
            return body
        time.sleep(1)
    raise AssertionError("FastAPI/Neo4j did not become ready")


@pytest.mark.skipif(
    not RUN_COMPOSE_INTEGRATION,
    reason="set RUN_COMPOSE_INTEGRATION=1 to run the isolated Docker smoke test",
)
def test_compose_recovers_same_analysis_run_after_redis_outage():
    environment = os.environ.copy()
    environment.update(
        {
            "WEB_PORT": "18080",
            "NEO4J_PORT": "17687",
            "REDIS_PORT": "16379",
            "NEO4J_PASSWORD": "task5-smoke-password",
            "AI_API_KEY": "unused-in-foundation",
            "DATA_ROOT": "/data",
        }
    )
    _compose(environment, "down", "--volumes", "--remove-orphans", check=False)
    try:
        _compose(environment, "up", "--build", "-d")
        project = _wait_for_project_api()

        _compose(environment, "stop", "worker", "redis")
        failed_status, failed_body = _upload(project["id"])
        assert failed_status == 500
        assert set(failed_body) == {"code", "request_id"}

        detail_status, detail = _json_request("GET", f"/api/projects/{project['id']}")
        assert detail_status == 200
        run = detail["analysisRuns"][0]
        assert run["status"] == "failed"
        assert run["errorCode"] == "api_error"
        assert run["retryable"] is True

        _compose(environment, "start", "redis")
        retry_path = f"/api/projects/{project['id']}/analysis-runs/{run['id']}/retry"
        first_retry = _json_request("POST", retry_path)
        second_retry = _json_request("POST", retry_path)
        assert first_retry == (202, {"analysisRunId": run["id"], "status": "queued"})
        assert second_retry == first_retry

        jobs = _compose(
            environment,
            "exec",
            "-T",
            "redis",
            "redis-cli",
            "--scan",
            "--pattern",
            "rq:job:ingest-*",
        ).stdout.splitlines()
        assert jobs == [f"rq:job:ingest-{run['id']}"]

        _compose(environment, "start", "worker")
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            _, detail = _json_request("GET", f"/api/projects/{project['id']}")
            current = detail["analysisRuns"][0]
            if current["status"] == "failed" and not current["retryable"]:
                break
            time.sleep(0.5)
        else:
            raise AssertionError("RQ worker did not process the recovered run")
        assert current["id"] == run["id"]
        assert current["errorCode"] == "conversion_error"
    finally:
        _compose(environment, "down", "--volumes", "--remove-orphans", check=False)
