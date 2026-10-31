"""The network live stream (TEN-059, DEC-548, DEC-132 item 4): GET /network/{network_id}/events.

The network variant of `routes_events`: it relays the network's own channel
(`network-board.updates`, qualified by the network scope, so another network's messages and the
tenant board's never reach it) as server-sent events. A message becomes `event: network-board` with
the time and nothing else: no figure, no service, no tenant.

The viewer is checked against the registry before the subscription opens (a network outside the
token's claim, a member who left and a role that never sees a network are the 404 of every other
network route) and again every `RECHECK_INTERVAL_SECONDS` while it is open. A viewer the registry
no longer lets in is sent one `scope-ended` event and the stream closes, so the token is not what
keeps a stream alive. The subscription is opened in the handler, before the response starts, so a
message published after the request is answered is not missed, and it is closed when the stream
ends or the client goes away. A keep-alive comment is sent when nothing has been published for
`KEEPALIVE_INTERVAL_SECONDS`.
"""

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from diucs.adapters.inbound.fhir_rest import routes_events
from diucs.adapters.inbound.fhir_rest.auth import require_role
from diucs.adapters.inbound.fhir_rest.routes_network import (
    NetworkId,
    ensure_in_claim,
    network_services,
)
from diucs.application.actor import Actor
from diucs.application.network_access import NETWORK_VIEW_ROLES, NetworkAccess
from diucs.application.ports.outbound.cache import NETWORK_BOARD_UPDATES_CHANNEL, Cache
from diucs.application.tenancy import bind_network
from diucs.application.use_cases.network_board_projector import NETWORK_BOARD_CHANGED
from diucs.domain.errors import NotAllowed, NotFound

KEEPALIVE_INTERVAL_SECONDS: float = routes_events.KEEPALIVE_INTERVAL_SECONDS
KEEPALIVE_LINE: Final = routes_events.KEEPALIVE_LINE
RECHECK_INTERVAL_SECONDS: float = 30.0
SCOPE_ENDED_EVENT: Final = "scope-ended"
_SCOPE_ENDED: Final = f"event: {SCOPE_ENDED_EVENT}\ndata: {{}}\n\n"

router = APIRouter()


def to_network_sse(message: object) -> str | None:
    """One server-sent event for a network board message, or None when it is not one."""
    if not isinstance(message, dict) or message.get("type") != NETWORK_BOARD_CHANGED:
        return None
    changed_at = routes_events._utc_time_text(message.get("at"))
    if changed_at is None:
        return None
    data = json.dumps({"changedAt": changed_at}, separators=(",", ":"))
    return f"event: network-board\ndata: {data}\n\n"


async def _still_a_member(access: NetworkAccess, actor: Actor, network_id: str) -> bool:
    try:
        await access.require_member(actor, network_id)
    except NotFound, NotAllowed:
        return False
    return True


async def _wall_still_allowed(access: NetworkAccess, actor: Actor, network_id: str) -> bool:
    """A wall screen is still allowed while its own record names this network and the registry
    lists its tenant as a member: a changed setting or a left network ends the stream (TEN-067)."""
    try:
        member = await access.require_wall(actor)
    except NotFound, NotAllowed:
        return False
    return member.network.id == network_id


async def network_events(
    messages: AsyncIterator[str],
    access: NetworkAccess,
    actor: Actor,
    network_id: str,
    *,
    still_allowed: Callable[[], Awaitable[bool]] | None = None,
) -> AsyncIterator[str]:
    """The stream: board events, keep-alives, and `scope-ended` once the registry says the viewer
    is no longer a member (then it ends). The read stays pending across ticks, so no message is lost
    to a timeout. Closes the subscription however it ends. `still_allowed` replaces the staff check
    for a viewer that is not staff (a wall screen)."""
    check = still_allowed or (lambda: _still_a_member(access, actor, network_id))
    loop = asyncio.get_running_loop()
    next_check = loop.time() + RECHECK_INTERVAL_SECONDS
    pending: asyncio.Future[str | None] | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(routes_events._next_message(messages))
            timeout = min(KEEPALIVE_INTERVAL_SECONDS, max(0.0, next_check - loop.time()))
            done, _ = await asyncio.wait({pending}, timeout=timeout)
            if loop.time() >= next_check:
                if not await check():
                    yield _SCOPE_ENDED
                    return
                next_check = loop.time() + RECHECK_INTERVAL_SECONDS
            if not done:
                yield KEEPALIVE_LINE
                continue
            raw = pending.result()
            pending = None
            if raw is None:
                return
            event = to_network_sse(routes_events.parse_message(raw))
            if event is not None:
                yield event
    finally:
        if pending is not None:
            pending.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pending
        await routes_events._close(messages)


def _cache(request: Request) -> Cache:
    # Fail closed: a missing cache is a configuration error (a 500), never an empty stream.
    cache: Cache | None = getattr(request.app.state, "cache", None)
    if cache is None:
        raise RuntimeError("no cache is configured for the live stream")
    return cache


@router.get("/network/{network_id}/events")
async def events(
    network_id: NetworkId,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*sorted(NETWORK_VIEW_ROLES)))],
) -> StreamingResponse:
    ensure_in_claim(actor, network_id)
    services = network_services(request)
    await services.access.require_member(actor, network_id)
    # The subscription takes the channel of the network scope bound here, and keeps it.
    with bind_network(network_id):
        messages = await _cache(request).subscribe(NETWORK_BOARD_UPDATES_CHANNEL)
    return StreamingResponse(
        network_events(messages, services.access, actor, network_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store"},
    )


async def open_wall_network_events(request: Request, actor: Actor) -> StreamingResponse:
    """The stream of a wall screen (TEN-067): the network is the one the screen's record names, so
    there is no path to ask with. The record is read before the subscription opens and again on
    every re-check."""
    services = network_services(request)
    member = await services.access.require_wall(actor)
    network_id = member.network.id
    with bind_network(network_id):
        messages = await _cache(request).subscribe(NETWORK_BOARD_UPDATES_CHANNEL)
    return StreamingResponse(
        network_events(
            messages,
            services.access,
            actor,
            network_id,
            still_allowed=lambda: _wall_still_allowed(services.access, actor, network_id),
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store"},
    )
