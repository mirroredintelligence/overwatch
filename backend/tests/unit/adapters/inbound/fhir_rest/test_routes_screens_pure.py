"""Pure tests of the wall screen pairing routes (R15). No Docker, no Neo4j.

Each test calls the app through an in-process transport. The container's unit-of-work factory
fails the test if it is ever opened: every refusal the routes make before a use case runs must open
no unit of work and write nothing. The tenant directory is a fake that records the hosts asked, so
a test can tell a route that looked the tenant up from one that answered without looking.
Synthetic values only: no patient data.
"""

import logging
import random
import re
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import Response

from diucs.adapters.inbound.fhir_rest import routes_screens
from diucs.adapters.inbound.fhir_rest.app import create_app
from diucs.adapters.inbound.fhir_rest.auth import BFF_SECRET_NAME
from diucs.adapters.inbound.fhir_rest.errors import NOT_FOUND_TEXT
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.adapters.testing.tokens import TEST_BFF_SECRET, issue_test_token
from diucs.application.ports.outbound.identity import DEVICE_TOKEN_SECRET
from diucs.application.ports.outbound.tenants import TenantRecordInvalid
from diucs.application.ports.outbound.tokens import LINK_TOKEN_SECRET
from diucs.application.tenancy import ScopeId, bind_tenant, current_scope_or_none
from diucs.application.use_cases.pair_wall_screen import (
    LIMIT_WINDOW,
    RATE_LIMITED_MESSAGE,
    AttemptLimiter,
    PairingRateLimited,
)
from diucs.domain.codes import Role
from diucs.domain.errors import NotAllowed
from diucs.domain.model.tenant import TenantStatus
from tests.support.tenant_samples import make_tenant

CLOCK = datetime(2026, 10, 23, 13, 2, tzinfo=UTC)
ACTIVE_HOST = "screens-a.example.test"
SUSPENDED_HOST = "screens-s.example.test"
DAMAGED_HOST = "screens-d.example.test"
UNKNOWN_HOST = "screens-x.example.test"
ADDRESS = "203.0.113.9"
OTHER_ADDRESS = "198.51.100.4"
TENANT = "example-icb"
START = "/screens/pairing"
SCREENS = "/screens"
SECRET_HEADER = {"X-Screen-Secret": "a-screen-secret-sample"}
REFUSED = "That code is not valid or has expired."
UNAVAILABLE = "Pairing is not available right now. Try again shortly."
SECRETS = {
    BFF_SECRET_NAME: TEST_BFF_SECRET,
    LINK_TOKEN_SECRET: b"pure-test-link-secret-for-the-pairing-routes",
    DEVICE_TOKEN_SECRET: b"pure-test-device-secret-for-the-pairing-routes",
}


class _Directory:
    """The tenant directory as the routes read it: `by_host`, and the hosts it was asked about."""

    def __init__(self) -> None:
        self.asked: list[str] = []
        self._by_host: dict[str, Any] = {
            ACTIVE_HOST: make_tenant(),
            SUSPENDED_HOST: make_tenant(TenantStatus.SUSPENDED),
            DAMAGED_HOST: TenantRecordInvalid("damaged tenant record"),
        }

    async def get(self, tenant_id: str) -> Any:
        """The record the bearer check reads (TEN-018): every tenant signed for here is active."""
        return make_tenant(id=tenant_id)

    async def by_host(self, host: str) -> Any:
        self.asked.append(host)
        value = self._by_host.get(host)
        if isinstance(value, Exception):
            raise value
        return value


class _DownCache:
    """A cache that cannot be reached: every operation raises, as a dropped connection would."""

    async def get(self, key: str) -> str | None:
        raise ConnectionError("cache host 10.0.0.5 refused the connection")

    async def set_if_absent(self, key: str, value: str, ttl: Any) -> bool:
        raise ConnectionError("cache host 10.0.0.5 refused the connection")

    async def delete(self, key: str) -> None:
        raise ConnectionError("cache host 10.0.0.5 refused the connection")


def _no_unit_of_work() -> Any:
    raise AssertionError("a unit of work was opened before the route refused")


class _Container:
    def __init__(self, *, secrets: Any = None, cache: Any = None) -> None:
        self.clock = FixedClock(CLOCK)
        self.ids = SequentialIds()
        self.uow_factory = _no_unit_of_work
        self.tenants = _Directory()
        self.secrets = secrets if secrets is not None else FixedSecretStore(SECRETS)
        self.cache = cache if cache is not None else InMemoryCache(self.clock)
        self.rng = random.Random(1)


def _client(container: _Container) -> httpx.AsyncClient:
    app = create_app(container)
    # The bearer check reads its secret store from the app, as the serving process sets it.
    app.state.secrets = container.secrets
    transport = httpx.ASGITransport(app=app, client=(ADDRESS, 4321))
    return httpx.AsyncClient(transport=transport, base_url=f"http://{ACTIVE_HOST}")


def _url(host: str, path: str) -> str:
    return f"http://{host}{path}"


def _diagnostics(response: httpx.Response) -> str:
    return str(response.json()["issue"][0]["diagnostics"])


def _request(address: str = ADDRESS) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": START,
            "headers": [],
            "client": (address, 4321),
            "server": (ACTIVE_HOST, 80),
            "scheme": "http",
            "query_string": b"",
        }
    )


def _lead_headers(key: str = "r15-connect-0001") -> dict[str, str]:
    token = issue_test_token(Role.LEAD, [], "lead-1")
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": key}


# Start: refusals before any unit of work opens.


async def test_a_start_to_a_host_no_tenant_owns_is_not_found_and_opens_nothing() -> None:
    container = _Container()
    async with _client(container) as client:
        response = await client.post(_url(UNKNOWN_HOST, START), json={})

    assert response.status_code == 404
    assert _diagnostics(response) == NOT_FOUND_TEXT
    assert response.headers["cache-control"] == "no-store"
    assert container.tenants.asked == [UNKNOWN_HOST]


async def test_a_start_to_a_suspended_tenant_is_not_found_and_opens_nothing() -> None:
    container = _Container()
    async with _client(container) as client:
        response = await client.post(_url(SUSPENDED_HOST, START), json={})

    assert response.status_code == 404
    assert _diagnostics(response) == NOT_FOUND_TEXT
    assert container.tenants.asked == [SUSPENDED_HOST]


async def test_a_start_to_a_damaged_tenant_record_is_not_found_not_guessed() -> None:
    container = _Container()
    async with _client(container) as client:
        response = await client.post(_url(DAMAGED_HOST, START), json={})

    assert response.status_code == 404
    assert _diagnostics(response) == NOT_FOUND_TEXT
    assert container.tenants.asked == [DAMAGED_HOST]


async def test_a_start_with_the_cache_down_answers_503_and_leaks_no_cache_detail() -> None:
    container = _Container(cache=_DownCache())
    async with _client(container) as client:
        response = await client.post(_url(ACTIVE_HOST, START), json={})

    assert response.status_code == 503
    assert response.json()["issue"][0]["code"] == "transient"
    assert _diagnostics(response) == UNAVAILABLE
    assert response.headers["retry-after"] == "30"
    assert response.headers["cache-control"] == "no-store"
    assert "10.0.0.5" not in response.text


async def test_a_start_with_the_pairing_secrets_missing_fails_closed_with_a_500() -> None:
    container = _Container(secrets=FixedSecretStore({}))
    async with _client(container) as client:
        response = await client.post(_url(ACTIVE_HOST, START), json={})

    assert response.status_code == 500
    assert container.tenants.asked == []


async def _use_up(container: _Container, key: str, limit: int) -> None:
    """Take every slot of a limit, in the tenant the routes bind (the cache scopes names to it)."""
    limiter = AttemptLimiter(container.cache)
    with bind_tenant(TENANT):
        for _ in range(limit):
            assert await limiter.take(key, limit, LIMIT_WINDOW) is not None


async def test_the_start_limit_for_one_address_answers_429_before_any_unit_opens() -> None:
    container = _Container()
    await _use_up(container, routes_screens._address_key(TENANT, "start", _request()), 20)

    async with _client(container) as client:
        response = await client.post(_url(ACTIVE_HOST, START), json={})

    assert response.status_code == 429
    assert response.json()["issue"][0]["code"] == "throttled"
    assert _diagnostics(response) == RATE_LIMITED_MESSAGE
    assert response.headers["retry-after"] == "600"
    assert response.headers["cache-control"] == "no-store"


# Claim: refusals before any unit of work opens.


async def test_a_claim_to_a_host_no_tenant_owns_is_the_one_refusal() -> None:
    container = _Container()
    async with _client(container) as client:
        response = await client.get(
            _url(UNKNOWN_HOST, f"{START}/pairing-sample"), headers=SECRET_HEADER
        )

    assert response.status_code == 404
    assert _diagnostics(response) == REFUSED
    assert container.tenants.asked == [UNKNOWN_HOST]


async def test_the_refused_claim_limit_answers_429_for_every_claim_from_that_address() -> None:
    container = _Container()
    key = routes_screens._address_key(TENANT, "claim-refused", _request())
    await _use_up(container, key, routes_screens.ADDRESS_REFUSED_CLAIMS)

    async with _client(container) as client:
        response = await client.get(
            _url(ACTIVE_HOST, f"{START}/pairing-sample"), headers=SECRET_HEADER
        )

    assert response.status_code == 429
    assert _diagnostics(response) == RATE_LIMITED_MESSAGE
    assert response.headers["retry-after"] == "600"


async def test_a_claim_with_the_cache_down_answers_503_and_issues_no_token() -> None:
    container = _Container(cache=_DownCache())
    async with _client(container) as client:
        response = await client.get(
            _url(ACTIVE_HOST, f"{START}/pairing-sample"), headers=SECRET_HEADER
        )

    assert response.status_code == 503
    assert _diagnostics(response) == UNAVAILABLE
    assert "deviceToken" not in response.text
    assert "10.0.0.5" not in response.text


# Connect: the role and the body, before the use case runs.


async def test_a_connect_by_an_advisor_is_the_non_revealing_not_found() -> None:
    container = _Container()
    token = issue_test_token(Role.ADVISOR, [], "advisor-1")
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "r15-advisor-0001"}
    async with _client(container) as client:
        response = await client.post(
            _url(ACTIVE_HOST, SCREENS),
            json={"code": "482913", "name": "Ward A wall"},
            headers=headers,
        )

    assert response.status_code == 404
    assert _diagnostics(response) == NOT_FOUND_TEXT


async def test_a_connect_runs_bound_to_the_leads_tenant_from_the_token() -> None:
    # R15 known issue closed by TEN-018: the lead's tenant is the signed claim, and the body, the
    # query, a header and the host (all naming another tenant here) are not read for it.
    seen: list[object] = []

    def record_scope_then_stop() -> Any:
        seen.append(current_scope_or_none())
        raise RuntimeError("stop here: the scope was recorded")

    container = _Container()
    container.uow_factory = record_scope_then_stop
    token = issue_test_token(Role.LEAD, [], "lead-1", tenant="tenant-lead")
    headers = {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": "r15-connect-0002",
        "X-Tenant": "tenant-other",
    }
    async with _client(container) as client:
        response = await client.post(
            _url(ACTIVE_HOST, SCREENS),
            json={"code": "482913", "name": "Ward A wall"},
            headers=headers,
            params={"tenant": "tenant-other"},
        )

    assert response.status_code == 500
    assert seen == [ScopeId.tenant("tenant-lead")]


async def test_a_connect_without_an_idempotency_key_is_refused_as_required() -> None:
    container = _Container()
    headers = {"Authorization": _lead_headers()["Authorization"]}
    async with _client(container) as client:
        response = await client.post(
            _url(ACTIVE_HOST, SCREENS),
            json={"code": "482913", "name": "Ward A wall"},
            headers=headers,
        )

    assert response.status_code == 400
    assert response.json()["issue"][0]["code"] == "required"


async def test_a_connect_that_names_a_tenant_is_refused_and_the_tenant_is_not_echoed() -> None:
    container = _Container()
    body = {"code": "482913", "name": "Ward A wall", "tenant": "tenant-b-sample-id"}
    async with _client(container) as client:
        response = await client.post(_url(ACTIVE_HOST, SCREENS), json=body, headers=_lead_headers())

    assert response.status_code == 400
    assert response.json()["issue"][0]["code"] == "invalid"
    assert "tenant-b-sample-id" not in response.text


async def test_a_connect_with_a_board_scope_other_than_tenant_or_network_is_refused() -> None:
    container = _Container()
    body = {"code": "482913", "name": "Ward A wall", "boardScope": "galaxy"}
    async with _client(container) as client:
        response = await client.post(_url(ACTIVE_HOST, SCREENS), json=body, headers=_lead_headers())

    assert response.status_code == 400


# The helpers, called directly.


def test_the_connect_body_defaults_to_the_tenant_board_and_refuses_any_other_field() -> None:
    body = routes_screens.ConnectScreenBody(code="482913", name="Ward A wall")

    assert body.boardScope == "tenant"
    with pytest.raises(ValidationError):
        routes_screens.ConnectScreenBody(code="482913", name="Ward A wall", tenant=TENANT)


def test_the_limit_key_holds_a_hash_of_the_address_and_never_the_address() -> None:
    key = routes_screens._address_key(TENANT, "start", _request())

    assert ADDRESS not in key
    assert re.fullmatch(rf"pairing-address:{TENANT}:start:[0-9a-f]{{32}}", key)


def test_the_limit_key_differs_by_tenant_by_kind_and_by_address() -> None:
    base = routes_screens._address_key(TENANT, "start", _request())

    assert base != routes_screens._address_key("tenant-b-sample-id", "start", _request())
    assert base != routes_screens._address_key(TENANT, "claim-refused", _request())
    assert base != routes_screens._address_key(TENANT, "start", _request(OTHER_ADDRESS))


def test_the_limits_and_the_refusal_words_are_the_prompt_values() -> None:
    assert routes_screens.REFUSED_TEXT == REFUSED
    assert routes_screens.ADDRESS_STARTS == 20
    assert routes_screens.ADDRESS_REFUSED_CLAIMS == 20
    assert routes_screens.RETRY_AFTER_UNAVAILABLE_SECONDS == 30
    assert LIMIT_WINDOW.total_seconds() == 600


async def test_a_cache_error_is_503_and_neither_its_text_nor_the_token_is_answered_or_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def run() -> Response:
        raise OSError("10.0.0.5 refused pairing token 482913")

    with caplog.at_level(logging.DEBUG):
        response = await routes_screens._answer(run)

    assert response.status_code == 503
    assert response.headers["retry-after"] == "30"
    assert b"10.0.0.5" not in response.body
    assert "482913" not in caplog.text
    assert "OSError" in caplog.text


async def test_a_rate_limit_is_429_with_the_window_as_retry_after() -> None:
    async def run() -> Response:
        raise PairingRateLimited(RATE_LIMITED_MESSAGE)

    response = await routes_screens._answer(run)

    assert response.status_code == 429
    assert response.headers["retry-after"] == "600"


async def test_a_refused_use_case_is_404_with_the_one_refusal_text_and_its_reason_is_dropped() -> (
    None
):
    async def run() -> Response:
        raise NotAllowed("a wrong secret for screen sample-123")

    response = await routes_screens._answer(run)

    assert response.status_code == 404
    assert REFUSED.encode() in response.body
    assert b"sample-123" not in response.body
