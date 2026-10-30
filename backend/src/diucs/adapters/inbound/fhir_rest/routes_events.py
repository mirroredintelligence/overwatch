"""The live-update stream for the wall board and the advisor screens (R06).

GET /events relays the cache's board.updates channel as server-sent events (contracts.md). The
stream stores nothing: a missed event is harmless because the open page refetches (architecture.md,
live updates). A message becomes `event: board` with the service and the time, and nothing else.

The subscription is opened in the handler, before the response starts, so a message published
after the request is answered is not missed (DEC-092). A keep-alive comment is sent when nothing has
been published for KEEPALIVE_INTERVAL_SECONDS, so proxies keep the connection open. When the
client goes away the subscription is closed (its aclose, see the Cache port), so the cache keeps
no subscriber for a stream that has ended.

The message rules are in DEC-111: the stream accepts the shape the board projector publishes
(`{"type": "board-changed", "service_id", "at"}`, DEC-099 item 8) and the shape the task names
(`serviceId`, optional `kind`, `changedAt`).
"""

import asyncio
import contextlib
import json
import re
from collections.abc import AsyncIterator, Mapping
from datetime import datetime
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from diucs.adapters.inbound.fhir_rest.auth import require_role
from diucs.application.actor import Actor, require_actor_in_bound_tenant
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


# A service id is a FHIR id (DEC-053 item 11). A changed time must be a UTC instant with an explicit
# zero offset, written Z or +00:00 (the projector writes +00:00), and a real calendar moment. It is
# sent with Z. Anything else is dropped, and the value is never echoed.
_SERVICE_ID: Final = re.compile(r"[A-Za-z0-9.-]{1,64}")
_UTC_TIME: Final = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|\+00:00)")


def _is_service_id(value: object) -> bool:
    return isinstance(value, str) and _SERVICE_ID.fullmatch(value) is not None


def _utc_time_text(value: object) -> str | None:
    if not isinstance(value, str) or _UTC_TIME.fullmatch(value) is None:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment.isoformat().replace("+00:00", "Z")


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
    text = _utc_time_text(changed_at)
    if not _is_service_id(service_id) or text is None:
        return None
    return service_id, kind, text


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


@router.get("/events")
async def events(
    request: Request, actor: Annotated[Actor, Depends(require_role(*STREAM_ROLES))]
) -> StreamingResponse:
    # The stream is the caller's scope only (TEN-039): the subscription below takes the channel of
    # the scope the token bound, and keeps it. An actor that is not of that scope is a wiring fault.
    require_actor_in_bound_tenant(actor)
    messages = await _cache(request).subscribe(BOARD_UPDATES_CHANNEL)
    return StreamingResponse(
        _events(messages),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store"},
    )
