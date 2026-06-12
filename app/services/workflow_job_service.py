"""异步 workflow job 管理。

本地原型实现：job 状态保存在进程内存中（单进程 uvicorn 足够），
真正的 workflow 结果仍由 ResearchWorkflowService 持久化到 SQLite。
多进程 / 分布式部署时应替换为 Redis/数据库支撑的任务队列。
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import threading
from typing import Any
from uuid import uuid4


class WorkflowJobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create_job(self, topic: str) -> str:
        job_id = f"job_{uuid4().hex[:12]}"
        with self._lock:
            self._jobs[job_id] = {
                "job_id": job_id,
                "status": WorkflowJobStatus.QUEUED.value,
                "topic": topic,
                "run_id": None,
                "error": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "finished_at": None,
            }
        return job_id

    def mark_running(self, job_id: str) -> None:
        self._update(job_id, status=WorkflowJobStatus.RUNNING.value)

    def mark_completed(
        self,
        job_id: str,
        run_id: str | None,
        success: bool,
        error: str | None = None,
    ) -> None:
        self._update(
            job_id,
            status=(
                WorkflowJobStatus.COMPLETED.value
                if success
                else WorkflowJobStatus.FAILED.value
            ),
            run_id=run_id,
            error=None if success else error,
            finished_at=datetime.now(timezone.utc).isoformat(),
        )

    def mark_failed(self, job_id: str, error: str, run_id: str | None = None) -> None:
        self._update(
            job_id,
            status=WorkflowJobStatus.FAILED.value,
            run_id=run_id,
            error=error,
            finished_at=datetime.now(timezone.utc).isoformat(),
        )

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def _update(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].update(fields)


workflow_job_store = WorkflowJobStore()
