"""The public return of an Entra administrator from the consent page (DEC-1316 item 5).

The route has no token and no tenant host. The tenant is named by the state and is only a routing
hint: the route binds it, the use case looks the invite up by the hash of the whole state inside it,
and every way of not finding one answers the same 404. `adminConsent` is passed on as what the
redirect said, never as proof. Synthetic values only.
"""

from types import SimpleNamespace
from typing import Any

import httpx

from overwatch.adapters.inbound.fhir_rest.app import create_app
from overwatch.adapters.inbound.fhir_rest.routes_admin_consent import PATH
from overwatch.adapters.testing.fixed_clock import FixedClock
from overwatch.adapters.testing.fixed_ids import SequentialIds
from overwatch.adapters.testing.memory_cache import InMemoryCache
from overwatch.application.tenancy import current_scope_or_none
from overwatch.application.use_cases.admin_consent import ConfirmResult
from overwatch.domain.errors import NotFound
from overwatch.domain.rules.admin_consent import EffectiveStatus, new_state
from tests.support.tenant_samples import T0


class _Service:
    def __init__(self, result: ConfirmResult | Exception) -> None:
        self.result = result
        self.calls: list[tuple[str | None, str, bool | None]] = []

    async def execute(self, state: str, *, admin_consent: bool | None) -> ConfirmResult:
        scope = current_scope_or_none()
        self.calls.append((None if scope is None else scope.value, state, admin_consent))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _client(service: Any) -> httpx.AsyncClient:
    clock = FixedClock(T0)
    container = SimpleNamespace(
        clock=clock, ids=SequentialIds(), platform_slots=InMemoryCache(clock)
    )
    app = create_app(container)  # type: ignore[arg-type]
    if service is not None:
        app.state.admin_consent_confirm = service
    transport = httpx.ASGITransport(
        app=app, client=("203.0.113.9", 4321), raise_app_exceptions=False
    )
    return httpx.AsyncClient(transport=transport, base_url="http://overwatch.example.test")


def test_the_path_is_public() -> None:
    assert PATH == "/admin-consent/confirmation"


async def test_the_tenant_the_state_names_is_bound_and_the_answer_is_the_use_cases() -> None:
    service = _Service(ConfirmResult(EffectiveStatus.CONSENTED, None, "New Organisation"))
    state = new_state("new-org")
    async with _client(service) as client:
        response = await client.post(PATH, json={"state": state, "adminConsent": True})

    assert response.status_code == 200
    assert response.json() == {
        "status": "consented",
        "reason": None,
        "organisation": "New Organisation",
    }
    assert response.headers["cache-control"] == "no-store"
    assert service.calls == [("new-org", state, True)]
    assert current_scope_or_none() is None  # nothing stays bound


async def test_a_pending_answer_carries_its_reason_in_words() -> None:
    service = _Service(ConfirmResult(EffectiveStatus.PENDING, "Not installed yet.", "Org"))
    async with _client(service) as client:
        response = await client.post(PATH, json={"state": new_state("new-org")})

    assert response.json()["status"] == "pending"
    assert response.json()["reason"] == "Not installed yet."
    assert service.calls[0][2] is None  # no flag given, none assumed


async def test_text_that_is_not_a_state_is_a_404_and_binds_and_asks_nothing() -> None:
    service = _Service(ConfirmResult(EffectiveStatus.CONSENTED, None))
    async with _client(service) as client:
        response = await client.post(PATH, json={"state": "not-a-state"})

    assert response.status_code == 404
    assert service.calls == []


async def test_an_invite_that_is_not_found_is_the_same_404() -> None:
    service = _Service(NotFound("no such invitation"))
    async with _client(service) as client:
        unknown = await client.post(PATH, json={"state": new_state("new-org")})
        malformed = await client.post(PATH, json={"state": "x"})

    assert unknown.status_code == malformed.status_code == 404
    assert unknown.content == malformed.content
    assert current_scope_or_none() is None


async def test_a_body_that_names_a_tenant_or_anything_else_is_refused() -> None:
    service = _Service(ConfirmResult(EffectiveStatus.CONSENTED, None))
    async with _client(service) as client:
        response = await client.post(
            PATH, json={"state": new_state("new-org"), "tenantId": "other-org"}
        )

    assert response.status_code in (400, 422)
    assert service.calls == []


async def test_an_unconfigured_process_fails_closed() -> None:
    async with _client(None) as client:
        response = await client.post(PATH, json={"state": new_state("new-org")})

    assert response.status_code == 500
