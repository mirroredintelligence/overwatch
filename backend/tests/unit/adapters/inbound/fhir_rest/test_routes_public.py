"""The public tenant profile route and the limiter in front of it (TEN-040).

The route has no token. The tenant is the one the request host names (DEC-134 item 3), the answer
holds display fields only, a host no tenant owns answers as a path that is not there, and the
source-address limiter is counted in the platform namespace, before the host is looked at.
Synthetic values only.
"""

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from diucs.adapters.inbound.fhir_rest.app import create_app
from diucs.adapters.inbound.fhir_rest.errors import NOT_FOUND_TEXT
from diucs.adapters.inbound.fhir_rest.routes_public import PROFILE_PATH
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.application.ports.outbound.tenants import TenantRecordInvalid
from diucs.application.rate_limits import PUBLIC_REQUESTS_PER_ADDRESS
from diucs.application.tenancy import current_scope, current_scope_or_none
from diucs.domain.model.tenant import (
    ConfigStatus,
    ContactKind,
    TenantConfig,
    TenantContact,
    TenantStatus,
)
from tests.support.tenant_samples import SAMPLE_WORDING, T0, make_tenant

NOW = datetime(2026, 10, 23, 13, 2, tzinfo=UTC)
HOST_A = "a.example.test"
HOST_B = "b.example.test"
SUSPENDED = "s.example.test"
DAMAGED = "d.example.test"
UNKNOWN = "x.example.test"
ADDRESS = "203.0.113.9"
OTHER_ADDRESS = "198.51.100.4"


class _Directory:
    def __init__(self) -> None:
        self.asked: list[str] = []
        self._by_host: dict[str, Any] = {
            HOST_A: make_tenant(id="tenant-a", display_name="Example A ICB"),
            HOST_B: make_tenant(id="tenant-b", display_name="Example B ICB"),
            SUSPENDED: make_tenant(TenantStatus.SUSPENDED, id="tenant-s"),
            DAMAGED: TenantRecordInvalid("damaged"),
        }

    async def by_host(self, host: str) -> Any:
        self.asked.append(host)
        value = self._by_host.get(host)
        if isinstance(value, Exception):
            raise value
        return value

    async def get(self, tenant_id: str) -> Any:
        return make_tenant(id=tenant_id)


class _Config:
    def __init__(self, config: TenantConfig | None, contacts: tuple[TenantContact, ...]) -> None:
        self._config = config
        self._contacts = contacts

    async def current_version(self) -> TenantConfig | None:
        return self._config

    async def contacts(self) -> tuple[TenantContact, ...]:
        return self._contacts


class _Unit:
    def __init__(self, config: _Config) -> None:
        self.unit_scope = current_scope()
        self.tenant_config = config

    async def __aenter__(self) -> _Unit:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


def _config(wording: bool = True) -> TenantConfig:
    values = dict(SAMPLE_WORDING) if wording else {}
    return TenantConfig(
        version=1,
        status=ConfigStatus.CURRENT,
        values=values,
        created_at=T0,
        created_by_ref="admin-ref-1",
        effective_from=T0,
    )


PHONE_A = TenantContact(ContactKind.COORDINATION_PHONE, "Coordination", "01234 567890")
EMAIL_A = TenantContact(ContactKind.SUPPORT_EMAIL, "Support", "support@example.test")
SHIFT_A = TenantContact(ContactKind.SHIFT_LEAD_ESCALATION, "Shift lead", "01234 000111")


class _Container:
    def __init__(self, *, slots: Any = "default") -> None:
        self.clock = FixedClock(NOW)
        self.ids = SequentialIds()
        self.tenants = _Directory()
        self.opened = 0
        self.platform_slots = InMemoryCache(self.clock) if slots == "default" else slots
        self.units: dict[str, _Config] = {
            "tenant-a": _Config(_config(), (EMAIL_A, SHIFT_A, PHONE_A)),
            "tenant-b": _Config(None, ()),
        }

    def uow_factory(self) -> _Unit:
        self.opened += 1
        return _Unit(self.units[str(current_scope().value)])


def _client(container: _Container, address: str = ADDRESS) -> httpx.AsyncClient:
    app = create_app(container)  # type: ignore[arg-type]
    transport = httpx.ASGITransport(app=app, client=(address, 4321), raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport)


def _url(host: str, path: str = PROFILE_PATH) -> str:
    return f"http://{host}{path}"


def test_the_path_is_under_public() -> None:
    assert PROFILE_PATH == "/public/tenant-profile"


async def test_a_known_host_gets_its_own_tenants_display_fields_only() -> None:
    container = _Container()
    async with _client(container) as client:
        response = await client.get(_url(HOST_A))

    assert response.status_code == 200
    assert response.json() == {
        "displayName": "Example A ICB",
        "timeZone": "Europe/London",
        "locale": "en-GB",
        "wording": {
            "systemName": SAMPLE_WORDING["systemName"],
            "referralSystemName": SAMPLE_WORDING["referralSystemName"],
            "coordinationTeamName": SAMPLE_WORDING["coordinationTeamName"],
        },
        "coordinationPhone": "01234 567890",
    }
    assert current_scope_or_none() is None


async def test_nothing_else_of_the_tenant_record_or_its_contacts_is_in_the_answer() -> None:
    container = _Container()
    async with _client(container) as client:
        text = (await client.get(_url(HOST_A))).text

    for hidden in (
        "tenant-a",
        "Example Integrated Care Board",
        "support@example.test",
        "01234 000111",
        "epoch",
    ):
        assert hidden not in text


async def test_a_tenant_with_no_configuration_answers_null_wording_and_phone() -> None:
    container = _Container()
    async with _client(container) as client:
        response = await client.get(_url(HOST_B))

    assert response.status_code == 200
    body = response.json()
    assert body["displayName"] == "Example B ICB"
    assert body["wording"] is None
    assert body["coordinationPhone"] is None


async def test_the_answer_is_not_cached_and_varies_by_host() -> None:
    container = _Container()
    async with _client(container) as client:
        response = await client.get(_url(HOST_A))

    assert response.headers["cache-control"] == "no-store"
    assert "host" in response.headers["vary"].lower()
    assert response.headers["x-content-type-options"] == "nosniff"


async def test_a_header_or_query_naming_another_tenant_changes_nothing() -> None:
    container = _Container()
    async with _client(container) as client:
        response = await client.get(
            _url(HOST_A) + "?tenant=tenant-b",
            headers={"X-Forwarded-Host": HOST_B, "X-Tenant": "tenant-b"},
        )

    assert response.json()["displayName"] == "Example A ICB"
    assert container.tenants.asked == [HOST_A]


@pytest.mark.parametrize("host", [UNKNOWN, SUSPENDED, DAMAGED])
async def test_an_unknown_suspended_or_damaged_host_answers_as_a_path_that_is_not_there(
    host: str,
) -> None:
    container = _Container()
    async with _client(container) as client:
        missing = await client.get(_url(HOST_A, "/public/nothing-here"))
        response = await client.get(_url(host))

    assert response.status_code == 404
    assert response.content == missing.content
    assert response.json()["issue"][0]["diagnostics"] == NOT_FOUND_TEXT
    assert container.opened == 0


async def test_only_get_is_routed() -> None:
    container = _Container()
    async with _client(container) as client:
        response = await client.post(_url(HOST_A), json={})

    assert response.status_code == 405


# The platform limiter


async def test_the_sixty_first_request_from_an_address_in_a_minute_is_throttled() -> None:
    container = _Container()
    async with _client(container) as client:
        statuses = [
            (await client.get(_url(HOST_A))).status_code
            for _ in range(PUBLIC_REQUESTS_PER_ADDRESS + 1)
        ]
        throttled = await client.get(_url(HOST_A))

    assert statuses[:-1] == [200] * PUBLIC_REQUESTS_PER_ADDRESS
    assert statuses[-1] == 429
    assert throttled.status_code == 429
    assert throttled.json()["issue"][0]["code"] == "throttled"
    assert throttled.headers["retry-after"] == "60"
    assert throttled.headers["cache-control"] == "no-store"


async def test_the_limit_is_counted_before_the_host_is_looked_at() -> None:
    container = _Container()
    async with _client(container) as client:
        for _ in range(PUBLIC_REQUESTS_PER_ADDRESS):
            await client.get(_url(UNKNOWN))
        asked = len(container.tenants.asked)
        response = await client.get(_url(HOST_A))

    assert response.status_code == 429
    assert len(container.tenants.asked) == asked
    assert container.opened == 0


async def test_another_address_is_counted_apart() -> None:
    container = _Container()
    async with _client(container) as one:
        for _ in range(PUBLIC_REQUESTS_PER_ADDRESS + 1):
            await one.get(_url(HOST_A))
    async with _client(container, OTHER_ADDRESS) as other:
        response = await other.get(_url(HOST_A))

    assert response.status_code == 200


async def test_the_window_ends_and_the_address_may_ask_again() -> None:
    container = _Container()
    async with _client(container) as client:
        for _ in range(PUBLIC_REQUESTS_PER_ADDRESS + 1):
            await client.get(_url(HOST_A))
        container.clock.advance(timedelta(minutes=1))
        response = await client.get(_url(HOST_A))

    assert response.status_code == 200


async def test_the_counts_are_in_the_platform_namespace_and_hold_a_hash_not_the_address() -> None:
    container = _Container()
    async with _client(container) as client:
        await client.get(_url(HOST_A))
        await client.get(_url(HOST_B))

    keys = container.platform_slots.platform_keys()
    assert len(keys) == 2
    digest = hashlib.sha256(ADDRESS.encode()).hexdigest()[:32]
    for key in keys:
        assert key.startswith("_:cache:")
        assert digest in key
        assert ADDRESS not in key
        assert "tenant-a" not in key
        assert "tenant-b" not in key


async def test_a_limiter_that_cannot_reach_its_cache_refuses_with_a_fixed_503() -> None:
    class _Down:
        async def platform_take(self, name: str, ttl: Any) -> bool:
            raise ConnectionError("cache host 10.0.0.5 refused the connection")

        async def platform_release(self, name: str) -> None:
            raise ConnectionError("cache host 10.0.0.5 refused the connection")

    container = _Container(slots=_Down())
    async with _client(container) as client:
        response = await client.get(_url(HOST_A))

    assert response.status_code == 503
    assert response.json()["issue"][0]["code"] == "transient"
    assert "10.0.0.5" not in response.text
    assert container.opened == 0


async def test_a_container_with_no_platform_slots_fails_closed_with_a_500() -> None:
    container = _Container(slots=None)
    async with _client(container) as client:
        response = await client.get(_url(HOST_A))

    assert response.status_code == 500
    assert container.opened == 0
