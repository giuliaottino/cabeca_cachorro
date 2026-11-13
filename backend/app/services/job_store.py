"""Armazenamento de jobs em memória, com limite de quantidade e tempo de vida.

O Space roda com um único processo (uvicorn sem workers extras); por isso um dicionário em memória
basta. Os jobs expiram para não esgotar a RAM do contêiner.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any

from app.config import settings


class JobStore:
    def __init__(self, max_jobs: int, ttl_seconds: int):
        self.max_jobs = max_jobs
        self.ttl = ttl_seconds
        self._items: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
        self._lock = threading.Lock()

    def _purge(self) -> None:
        now = time.time()
        for key in [k for k, (ts, _) in self._items.items() if now - ts > self.ttl]:
            del self._items[key]
        while len(self._items) > self.max_jobs:
            self._items.popitem(last=False)

    def put(self, job_id: str, job: dict[str, Any]) -> None:
        with self._lock:
            self._items[job_id] = (time.time(), job)
            self._purge()

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            self._purge()
            item = self._items.get(job_id)
            return item[1] if item else None

    def __len__(self) -> int:
        return len(self._items)


JOBS = JobStore(settings.max_jobs, settings.job_ttl_hours * 3600)
