"""Outbound port: the replies the webhook could not take in (DEC-1359).

One record per message sid. `add` is idempotent (a second failure of the same message keeps the
first record). `list_open` is newest first and capped. Written best-effort by the webhook in a unit
of work of its own, and read by the shift lead.
"""

from datetime import datetime
from typing import Protocol

from overwatch.domain.model.inbound_reply import InboundReplyFailure, Resolution

__all__ = ["InboundReplyFailures"]


class InboundReplyFailures(Protocol):
    async def add(self, failure: InboundReplyFailure) -> bool:
        """Keep the failure. True when this call made the record, False when the message already
        had one (nothing is changed)."""
        ...

    async def list_open(self) -> list[InboundReplyFailure]:
        """The open failures, newest first, at most `LIST_MAX`."""
        ...

    async def get(self, sid: str) -> InboundReplyFailure | None: ...

    async def mark_resolved(
        self, sid: str, *, resolution: Resolution, by: str, at: datetime
    ) -> bool:
        """Close an open failure. True when this call closed it, False when it was not open or
        does not exist."""
        ...
