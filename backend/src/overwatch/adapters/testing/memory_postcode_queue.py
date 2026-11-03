"""An in-memory download queue for the route and worker tests (DEC-1329). It keeps the same states
as the platform statements (queued, running, done, failed) and calls no database."""

from datetime import datetime
from typing import Any


class MemoryPostcodeQueue:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    async def request(self, prefix: str, now: datetime) -> None:
        self.rows[prefix] = {"status": "queued", "requestedAt": now}

    async def claim_next(self, now: datetime) -> str | None:
        queued = sorted(
            (prefix for prefix, row in self.rows.items() if row["status"] == "queued"),
            key=lambda prefix: self.rows[prefix]["requestedAt"],
        )
        if not queued:
            return None
        self.rows[queued[0]]["status"] = "running"
        return queued[0]

    async def finish(self, prefix: str, postcodes: int, now: datetime) -> None:
        self.rows[prefix].update(status="done", postcodes=postcodes)

    async def fail(self, prefix: str, now: datetime) -> None:
        self.rows[prefix]["status"] = "failed"
