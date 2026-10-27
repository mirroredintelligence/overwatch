"""The live-update stream for the wall board and the advisor screens (R06).

GET /events relays the cache's board.updates channel as server-sent events (contracts.md). The
stream stores nothing: a missed event is harmless because the open page refetches (architecture.md,
live updates). A message becomes `event: board` with the service and the time, and nothing else.

The subscription is opened in the handler, before the response starts, so a message published
after the request is answered is not missed (DEC-092). A keep-alive comment is sent when nothing has
been published for KEEPALIVE_INTERVAL_SECONDS, so proxies keep the connection open. When the
client goes away the subscription is closed (its aclose, see the Cache port), so the cache keeps
no subscriber for a stream that has ended.

The message rules are in DEC-110: the stream accepts the shape the board projector publishes
(`{"type": "board-changed", "service_id", "at"}`, DEC-099 item 8) and the shape the task names
(`serviceId`, optional `kind`, `changedAt`).
"""

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator, Mapping
from typing import Any, Final

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from diucs.adapters.inbound.fhir_rest.auth import require_role
from diucs.application.ports.outbound.cache import BOARD_UPDATES_CHANNEL, Cache
from diucs.application.use_cases.board_projector import BOARD_CHANGED
from diucs.domain.codes import Role

KEEPALIVE_INTERVAL_SECONDS: Final[float] = 15.0
KEEPALIVE_LINE: Final = ": keep-alive\n\n"
STREAM_ROLES: Final = (Role.WALL, Role.ADVISOR, Role.CLINICAL, Role.LEAD, Role.EXEC)
KINDS: Final = frozenset({"capacity", "status", "booking"})

router = APIRouter()


def parse_message(text: str) -> object | None:
    """Decode one channel message. Text that is not JSON is not a message."""
    try:
        value: object = json.loads(text)
    except ValueError, RecursionError:
        return None
    return value


def _fields(message: object) -> tuple[str, str | None, str] | None:
    """The service, the optional kind and the time of a board message, or None to drop it."""
    if not isinstance(message, Mapping):
        return None
    if "type" in message:
        # The board projector's message (DEC-099 item 8). It carries no kind.
        if message["type"] != BOARD_CHANGED:
            return None
        service_id: Any = message.get("service_id")
        changed_at: Any = message.get("at")
        kind: str | None = None
    else:
        service_id = message.get("serviceId")
        changed_at = message.get("changedAt")
        kind = None
        if "kind" in message:
            if not isinstance(message["kind"], str) or message["kind"] not in KINDS:
                return None
            kind = message["kind"]
    if not isinstance(service_id, str) or not service_id:
        return None
    if not isinstance(changed_at, str) or not changed_at:
        return None
    return service_id, kind, changed_at


def to_sse(message: object) -> str | None:
    """One server-sent event for a board message, or None when the message is not a board event.

    The event carries only the service id, the kind when the message has one, and the time.
    """
    fields = _fields(message)
    if fields is None:
        return None
    service_id, kind, changed_at = fields
    data: dict[str, str] = {"serviceId": service_id}
    if kind is not None:
        data["kind"] = kind
    data["changedAt"] = changed_at
    return f"event: board\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


async def _next_message(messages: AsyncIterator[str]) -> str | None:
    try:
        return await messages.__anext__()
    except StopAsyncIteration:
        return None


async def _close(messages: AsyncIterator[str]) -> None:
    aclose = getattr(messages, "aclose", None)
    if aclose is not None:
        await aclose()


async def _events(messages: AsyncIterator[str]) -> AsyncIterator[str]:
    # The read stays pending across keep-alive ticks, so no message is lost to a timeout.
    pending: asyncio.Future[str | None] | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(_next_message(messages))
            done, _ = await asyncio.wait({pending}, timeout=KEEPALIVE_INTERVAL_SECONDS)
            if not done:
                yield KEEPALIVE_LINE
                continue
            raw = pending.result()
            pending = None
            if raw is None:
                return
            event = to_sse(parse_message(raw))
            if event is not None:
                yield event
    finally:
        if pending is not None:
            pending.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pending
        await _close(messages)


def _cache(request: Request) -> Cache:
    # Fail closed: a missing cache is a configuration error (a 500), never an empty stream.
    cache: Cache | None = getattr(request.app.state, "cache", None)
    if cache is None:
        raise RuntimeError("no cache is configured for the live stream")
    return cache


@router.get("/events", dependencies=[Depends(require_role(*STREAM_ROLES))])
async def events(request: Request) -> StreamingResponse:
    messages = await _cache(request).subscribe(BOARD_UPDATES_CHANNEL)
    return StreamingResponse(
        _events(messages),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store"},
    )
