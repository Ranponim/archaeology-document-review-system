import os
import re
from typing import Protocol

from redis import Redis
from rq import Queue, Retry
from rq.exceptions import DuplicateJobError

SAFE_ANALYSIS_RUN_ID = re.compile(r"[A-Za-z0-9_-]+")


class QueuePort(Protocol):
    def fetch_job(self, job_id: str): ...

    def enqueue(self, function_name: str, *args, **kwargs): ...


def create_queue() -> Queue:
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    return Queue("default", connection=Redis.from_url(redis_url))


def enqueue_ingest(
    analysis_run_id: str,
    *,
    queue: QueuePort | None = None,
) -> str:
    """Enqueue a run once using a deterministic RQ job identifier."""
    if SAFE_ANALYSIS_RUN_ID.fullmatch(analysis_run_id) is None:
        raise ValueError("analysis_run_id contains unsupported characters")

    target_queue = queue if queue is not None else create_queue()
    job_id = f"ingest-{analysis_run_id}"
    existing = target_queue.fetch_job(job_id)
    if existing is not None:
        return existing.id

    try:
        job = target_queue.enqueue(
            "app.jobs.worker.run_ingest_job",
            analysis_run_id,
            job_id=job_id,
            unique=True,
            retry=Retry(max=3, interval=[10, 30, 60]),
            result_ttl=86_400,
            failure_ttl=604_800,
        )
    except DuplicateJobError:
        job = target_queue.fetch_job(job_id)
        if job is None:
            raise
    return job.id


def enqueue_ai_analysis(
    analysis_run_id: str,
    project_id: str,
    model: str,
    *,
    queue: QueuePort | None = None,
) -> str:
    """Enqueue an AI analysis run once using a deterministic RQ job identifier."""
    if SAFE_ANALYSIS_RUN_ID.fullmatch(analysis_run_id) is None:
        raise ValueError("analysis_run_id contains unsupported characters")

    target_queue = queue if queue is not None else create_queue()
    job_id = f"ai-analysis-{analysis_run_id}"
    existing = target_queue.fetch_job(job_id)
    if existing is not None:
        return existing.id

    try:
        job = target_queue.enqueue(
            "app.jobs.worker.run_ai_analysis_job",
            analysis_run_id,
            project_id,
            model,
            job_id=job_id,
            unique=True,
            retry=Retry(max=3, interval=[10, 30, 60]),
            result_ttl=86_400,
            failure_ttl=604_800,
        )
    except DuplicateJobError:
        job = target_queue.fetch_job(job_id)
        if job is None:
            raise
    return job.id
