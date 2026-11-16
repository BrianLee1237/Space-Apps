"""Bounded, deduplicated local analysis jobs with cooperative cancellation."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from uuid import uuid4

from .archive import CapacityError
from .storage import canonical, digest


class JobCancelled(Exception):
    pass


@dataclass
class Job:
    id: str
    key: str
    created: float
    state: str = "queued"
    completed: int = 0
    total: int = 0
    message: str = "Queued"
    result: dict | None = None
    error: str | None = None
    subscribers: set = field(default_factory=set)
    cancel: threading.Event = field(default_factory=threading.Event)


class JobManager:
    def __init__(self, workers=2, capacity=12, retention=900):
        self.executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="science")
        self.lock = threading.RLock()
        self.jobs = {}
        self.by_key = {}
        self.capacity = capacity
        self.retention = retention

    def submit(self, kind, parameters, function, reusable=None):
        key = digest(canonical({"kind": kind, "parameters": parameters}))
        with self.lock:
            now = time.time()
            for job_id, previous in list(self.jobs.items()):
                if previous.state in {"complete", "failed", "cancelled"}:
                    if now - previous.created > self.retention:
                        self.jobs.pop(job_id)
                        if self.by_key.get(previous.key) == job_id:
                            self.by_key.pop(previous.key, None)
            existing = self.jobs.get(self.by_key.get(key))
            token = uuid4().hex
            valid = (
                not existing
                or existing.state != "complete"
                or not reusable
                or reusable(existing.result)
            )
            if (
                existing
                and existing.state in {"queued", "running", "complete"}
                and valid
                and not existing.cancel.is_set()
            ):
                existing.subscribers.add(token)
                return self.snapshot(existing.id), token
            active = sum(job.state in {"queued", "running"} for job in self.jobs.values())
            if active >= self.capacity:
                raise CapacityError("Analysis queue is full. Wait for an active job to finish.")
            job = Job(uuid4().hex, key, now)
            job.subscribers.add(token)
            self.jobs[job.id] = job
            self.by_key[key] = job.id
            self.executor.submit(self._run, job, function)
            return self.snapshot(job.id), token

    def _run(self, job, function):
        def cancelled():
            if job.cancel.is_set():
                raise JobCancelled()

        def progress(completed, total, message):
            cancelled()
            with self.lock:
                job.completed, job.total, job.message = completed, total, message

        try:
            cancelled()
            with self.lock:
                job.state, job.message = "running", "Preparing analysis"
            result = function(progress, cancelled)
            canonical(result)  # Reject non-finite or unserializable results before publication.
            cancelled()
            with self.lock:
                job.result, job.state, job.message = result, "complete", "Complete"
                job.created = time.time()
        except JobCancelled:
            with self.lock:
                job.state, job.message = "cancelled", "Cancelled"
                job.created = time.time()
        except Exception as exc:
            with self.lock:
                job.state, job.error, job.message = "failed", str(exc), "Analysis failed"
                job.created = time.time()

    def snapshot(self, job_id):
        with self.lock:
            job = self.jobs[job_id]
            return {
                "id": job.id,
                "state": job.state,
                "completed": job.completed,
                "total": job.total,
                "message": job.message,
                "result": job.result,
                "error": job.error,
            }

    def release(self, job_id, token):
        with self.lock:
            job = self.jobs[job_id]
            job.subscribers.discard(token)
            if not job.subscribers and job.state in {"queued", "running"}:
                job.cancel.set()
            return self.snapshot(job_id)

    def close(self):
        with self.lock:
            for job in self.jobs.values():
                job.cancel.set()
        self.executor.shutdown(wait=False, cancel_futures=True)
