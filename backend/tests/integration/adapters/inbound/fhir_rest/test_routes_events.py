"""The live-update stream over HTTP (R06): the event, the keep-alive, the roles and the cleanup.

Runs on the harness Neo4j (DEC-004) through api_app. httpx's ASGI transport waits for the whole
body, and a stream never ends, so these tests drive the ASGI app directly (_Stream) and read the
body while the response is still open. The end-to-end case writes a report through the real board
projector (U09) and expects one event for that service.
"""

import asyncio
import json
from collections.abc import Callable, MutableMapping
from datetime import UTC, datetime, time
from typing import Any

import pytest
from fastapi import FastAPI

from diucs.adapters.inbound.fhir_rest import routes_events
from diucs.adapters.inbound.fhir_rest.auth import BFF_SECRET_NAME
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.adapters.testing.tokens import TEST_BFF_SECRET, issue_test_token
from diucs.application.ports.outbound.cache import BOARD_UPDATES_CHANNEL
from diucs.application.use_cases.board_projector import BoardProjector
from diucs.application.use_cases.query_board import QueryBoard
from diucs.bootstrap.container import Container
from diucs.domain.codes import Cadence, Channel, Measure, ReportSource, ReportType, Role
from diucs.domain.codes import ServiceCategory as Category
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.service import AvailableTime, ServiceProfile
from tests.support.api import R01_TEST_NOW

pytestmark = pytest.mark.asyncio(loop_scope="session")

BOARD_ROLES = (Role.WALL, Role.ADVISOR, Role.CLINICAL, Role.LEAD, Role.EXEC)
EVENT_TEXT = (
    'event: board\ndata: {"serviceId":"svc-1","kind":"capacity",'
    '"changedAt":"2026-10-23T13:12:00Z"}\n\n'
)
PROJECTOR_EVENT_TEXT = (
    'event: board\ndata: {"serviceId":"svc-1","changedAt":"2026-10-23T13:12:00Z"}\n\n'
)
PUBLISHED_BOARD = json.dumps(
    {"serviceId": "svc-1", "kind": "capacity", "changedAt": "2026-10-23T13:12:00Z"}
)
PUBLISHED_PROJECTOR = json.dumps(
    {"type": "board-changed", "service_id": "svc-1", "at": "2026-10-23T13:12:00Z"}
)


def _wall_headers() -> dict[str, str]:
    token = issue_test_token(Role.WALL, [], "device-wall-1")
    return {"authorization": f"Bearer {token}"}


def _headers_for(role: Role) -> dict[str, str]:
    return {"authorization": f"Bearer {issue_test_token(role, [], 'prac-1')}"}


class _Stream:
    """One GET /events, driven at the ASGI level so the body can be read while it is open."""

    def __init__(self, app: FastAPI, headers: dict[str, str], log: list[str] | None = None) -> None:
        self._app = app
        self._headers = headers
        self._log = log
        self._body_sent = False
        self._closed = asyncio.Event()
        self._started = asyncio.Event()
        self._chunks: list[bytes] = []
        self.status: int | None = None
        self.response_headers: dict[str, str] = {}
        self._task: asyncio.Future[None] | None = None

    def _scope(self) -> dict[str, Any]:
        return {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/events",
            "raw_path": b"/events",
            "root_path": "",
            "query_string": b"",
            "headers": [(k.encode(), v.encode()) for k, v in self._headers.items()],
            "client": ("testclient", 50000),
            "server": ("test", 80),
        }

    async def _receive(self) -> dict[str, Any]:
        if not self._body_sent:
            self._body_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await self._closed.wait()
        return {"type": "http.disconnect"}

    async def _send(self, message: MutableMapping[str, Any]) -> None:
        if message["type"] == "http.response.start":
            self.status = message["status"]
            self.response_headers = {
                key.decode().lower(): value.decode() for key, value in message["headers"]
            }
            if self._log is not None:
                self._log.append("start")
            self._started.set()
        elif message["type"] == "http.response.body":
            self._chunks.append(message.get("body", b""))

    def text(self) -> str:
        return b"".join(self._chunks).decode()

    async def read_until(self, expected: str, timeout: float = 2.0) -> str:
        try:
            async with asyncio.timeout(timeout):
                while expected not in self.text():
                    await asyncio.sleep(0.01)
        except TimeoutError:
            raise AssertionError(
                f"expected {expected!r} in the stream within {timeout} s, got {self.text()!r}"
            ) from None
        return self.text()

    async def __aenter__(self) -> _Stream:
        self._task = asyncio.ensure_future(self._app(self._scope(), self._receive, self._send))
        async with asyncio.timeout(2.0):
            await self._started.wait()
        return self

    async def __aexit__(self, *exc: object) -> None:
        self._closed.set()
        if self._task is not None:
            await asyncio.wait_for(self._task, timeout=2.0)


async def _eventually(check: Callable[[], bool], timeout: float = 2.0) -> None:
    async with asyncio.timeout(timeout):
        while not check():
            await asyncio.sleep(0.01)


@pytest.fixture
def stream_cache() -> InMemoryCache:
    return InMemoryCache(FixedClock(R01_TEST_NOW))


@pytest.fixture
def stream_app(api_app: FastAPI, stream_cache: InMemoryCache) -> FastAPI:
    """The API with the synthetic BFF secret and the in-memory cache the stream relays."""
    api_app.state.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})
    api_app.state.cache = stream_cache
    return api_app


async def test_the_stream_is_served_as_event_stream_and_not_stored(
    stream_app: FastAPI,
) -> None:
    async with _Stream(stream_app, _wall_headers()) as stream:
        assert stream.status == 200
        assert stream.response_headers["content-type"].startswith("text/event-stream")
        assert stream.response_headers["cache-control"] == "no-store"


@pytest.mark.parametrize("role", BOARD_ROLES, ids=lambda role: role.value)
async def test_each_board_role_may_open_the_stream(stream_app: FastAPI, role: Role) -> None:
    async with _Stream(stream_app, _headers_for(role)) as stream:
        assert stream.status == 200


async def test_a_board_message_is_sent_as_one_event(
    stream_app: FastAPI, stream_cache: InMemoryCache
) -> None:
    async with _Stream(stream_app, _wall_headers()) as stream:
        await stream_cache.publish(BOARD_UPDATES_CHANNEL, PUBLISHED_BOARD)
        await stream.read_until(EVENT_TEXT)

    assert stream.text() == EVENT_TEXT


async def test_a_keep_alive_comment_is_sent_when_nothing_is_published(
    stream_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(routes_events, "KEEPALIVE_INTERVAL_SECONDS", 0.05)

    async with _Stream(stream_app, _wall_headers()) as stream:
        await stream.read_until(": keep-alive\n\n")

    assert stream.text().startswith(": keep-alive\n\n")


@pytest.mark.parametrize(
    "role", [Role.REPORTER, Role.OWNER, Role.AUDIT, Role.SUPPORT, Role.ANONYMOUS_LINK]
)
async def test_a_role_outside_the_board_gets_a_404(stream_app: FastAPI, role: Role) -> None:
    # The same path opens for a wall token, so the 404 below is the role's refusal and not a
    # missing route. The refused request is read as a stream too: a route that wrongly opened
    # the stream would otherwise keep the test waiting for a body that never ends.
    async with _Stream(stream_app, _wall_headers()) as wall:
        assert wall.status == 200
    async with _Stream(stream_app, _headers_for(role)) as refused:
        assert refused.status == 404
        await refused.read_until('"code":"not-found"')


async def test_a_request_without_a_token_is_refused(stream_app: FastAPI) -> None:
    # Read as a stream, with the response start bounded by _Stream's timeout. Through httpx a
    # missing role gate would open a stream that never ends, and the test would hang instead of
    # failing. Here it fails on the status within the timeout.
    async with _Stream(stream_app, {}) as stream:
        assert stream.status == 401
        assert stream.response_headers["www-authenticate"] == "Bearer"


async def test_the_subscription_is_opened_before_the_response_starts(
    stream_app: FastAPI, stream_cache: InMemoryCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A stream that subscribed only when its body is first read would miss a message published as
    # the response begins. The subscription must exist before the response starts (DEC-111 item 4).
    log: list[str] = []
    subscribe = stream_cache.subscribe

    async def logged_subscribe(channel: str) -> Any:
        log.append("subscribe")
        return await subscribe(channel)

    monkeypatch.setattr(stream_cache, "subscribe", logged_subscribe)

    async with _Stream(stream_app, _wall_headers(), log) as stream:
        assert stream.status == 200

    assert log == ["subscribe", "start"]


async def test_closing_the_stream_removes_its_subscription(
    stream_app: FastAPI, stream_cache: InMemoryCache
) -> None:
    async with _Stream(stream_app, _wall_headers()):
        assert stream_cache.subscriber_count(BOARD_UPDATES_CHANNEL) == 1

    await _eventually(lambda: stream_cache.subscriber_count(BOARD_UPDATES_CHANNEL) == 0)


async def test_a_projector_message_reaches_an_open_stream_as_an_event_without_a_kind(
    stream_app: FastAPI, stream_cache: InMemoryCache
) -> None:
    async with _Stream(stream_app, _wall_headers()) as stream:
        await stream_cache.publish(BOARD_UPDATES_CHANNEL, PUBLISHED_PROJECTOR)
        await stream.read_until(PROJECTOR_EVENT_TEXT)

    assert stream.text() == PROJECTOR_EVENT_TEXT


async def test_messages_that_are_not_board_events_are_not_sent(
    stream_app: FastAPI, stream_cache: InMemoryCache
) -> None:
    async with _Stream(stream_app, _wall_headers()) as stream:
        await stream_cache.publish(BOARD_UPDATES_CHANNEL, "not json")
        await stream_cache.publish(BOARD_UPDATES_CHANNEL, '{"type": "other", "at": "x"}')
        await stream_cache.publish(
            BOARD_UPDATES_CHANNEL,
            '{"serviceId": "svc-1", "kind": "weather", "changedAt": "2026-10-23T13:12:00Z"}',
        )
        await stream_cache.publish(BOARD_UPDATES_CHANNEL, PUBLISHED_BOARD)
        await stream.read_until(EVENT_TEXT)

    assert stream.text() == EVENT_TEXT


def _ucr_west() -> ServiceProfile:
    return ServiceProfile(
        id="svc-ucr-west",
        name="UCR West",
        category=Category.URGENT_COMMUNITY_RESPONSE,
        measure=Measure.REFERRALS_ACCEPTABLE,
        unit_label="referrals",
        established_capacity=8,
        can_exceed_established=False,
        usual_range=(0, 8),
        cadence=Cadence.EVERY_2_HRS,
        available_times=(AvailableTime.weekdays(time(8, 0), time(20, 0)),),
        channel=Channel.TEXT,
        limited_level_percent=80,
    )


async def test_a_capacity_report_written_through_the_board_projector_streams_one_event(
    stream_app: FastAPI, stream_cache: InMemoryCache, test_container: Container
) -> None:
    clock = FixedClock(R01_TEST_NOW)
    west = _ucr_west()
    async with test_container.uow_factory() as uow:
        await uow.services.save(west)
        await uow.capacity.add(
            CapacityReport(
                id="obs-west-1303",
                service_id=west.id,
                value=4,
                measure=west.measure,
                effective_at=datetime(2026, 10, 23, 13, 3, tzinfo=UTC),
                source=ReportSource.TEXT,
                report_type=ReportType.NUMBER,
            )
        )
        await uow.commit()
    projector = BoardProjector(QueryBoard(test_container.uow_factory, clock), stream_cache, clock)

    async with _Stream(stream_app, _wall_headers()) as stream:
        handled = await projector.handle(
            "CapacityReported",
            {
                "service_id": west.id,
                "report_id": "obs-west-1303",
                "value": 4,
                "at": "2026-10-23T13:03:00Z",
            },
        )
        await stream.read_until('"serviceId":"svc-ucr-west"')

    assert handled is True
    events = [part for part in stream.text().split("\n\n") if part.startswith("event: board")]
    assert len(events) == 1
    data: dict[str, Any] = json.loads(events[0].split("data: ", 1)[1])
    assert set(data) == {"serviceId", "changedAt"}
    assert data["serviceId"] == "svc-ucr-west"
    assert datetime.fromisoformat(data["changedAt"].replace("Z", "+00:00")) == R01_TEST_NOW


# Two tenants (TEN-039, DEC-132): a stream is the caller's scope only.


def _headers_of(tenant: str) -> dict[str, str]:
    token = issue_test_token(Role.WALL, [], "device-wall-x", tenant=tenant)
    return {"authorization": f"Bearer {token}"}


async def test_a_tenants_stream_gets_its_own_tenants_events_and_never_the_others(
    stream_app: FastAPI, stream_cache: InMemoryCache, tenant_id: str, other_tenant_id: str
) -> None:
    from tests.support.tenancy import as_tenant

    async with (
        _Stream(stream_app, _headers_of(tenant_id)) as first,
        _Stream(stream_app, _headers_of(other_tenant_id)) as second,
    ):
        with as_tenant(other_tenant_id):
            await stream_cache.publish(BOARD_UPDATES_CHANNEL, PUBLISHED_PROJECTOR)
        await second.read_until(PROJECTOR_EVENT_TEXT)
        await asyncio.sleep(0.2)
        assert first.text() == ""

        with as_tenant(tenant_id):
            await stream_cache.publish(BOARD_UPDATES_CHANNEL, PUBLISHED_BOARD)
        await first.read_until(EVENT_TEXT)
        await asyncio.sleep(0.2)

    assert first.text() == EVENT_TEXT
    assert second.text() == PROJECTOR_EVENT_TEXT


async def test_a_stream_holds_one_subscription_in_its_own_tenants_scope(
    stream_app: FastAPI, stream_cache: InMemoryCache, tenant_id: str, other_tenant_id: str
) -> None:
    from tests.support.tenancy import as_tenant

    async with _Stream(stream_app, _headers_of(other_tenant_id)):
        with as_tenant(other_tenant_id):
            assert stream_cache.subscriber_count(BOARD_UPDATES_CHANNEL) == 1
        with as_tenant(tenant_id):
            assert stream_cache.subscriber_count(BOARD_UPDATES_CHANNEL) == 0
