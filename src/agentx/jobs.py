from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class PromptJob:
    id: int
    prompt: str
    created_at: str


class PromptJobQueue:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._pending: deque[PromptJob | None] = deque()
        self._next_id = 1
        self.current: PromptJob | None = None

    def submit(self, prompt: str) -> PromptJob:
        with self._condition:
            job = PromptJob(
                id=self._next_id,
                prompt=prompt,
                created_at=datetime.now().isoformat(timespec="seconds"),
            )
            self._next_id += 1
            self._pending.append(job)
            self._condition.notify()
            return job

    def stop(self) -> None:
        with self._condition:
            self._pending.append(None)
            self._condition.notify()

    def get(self) -> PromptJob | None:
        with self._condition:
            while not self._pending:
                self._condition.wait()
            job = self._pending.popleft()
            self.current = job
            return job

    def complete_current(self) -> None:
        with self._condition:
            self.current = None

    def cancel_pending(self, job_id: int | None = None) -> list[PromptJob]:
        with self._condition:
            cancelled: list[PromptJob] = []
            kept: deque[PromptJob | None] = deque()
            for job in self._pending:
                if job is None:
                    kept.append(job)
                    continue
                if job_id is None or job.id == job_id:
                    cancelled.append(job)
                else:
                    kept.append(job)
            self._pending = kept
            return cancelled

    def pending(self) -> list[PromptJob]:
        with self._condition:
            return [job for job in self._pending if job is not None]

    def pending_count(self) -> int:
        with self._condition:
            return sum(1 for job in self._pending if job is not None)
