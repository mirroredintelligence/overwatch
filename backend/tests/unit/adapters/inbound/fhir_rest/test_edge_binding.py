"""The REST edge binds the tenant from the verified token and from nothing else (TEN-018).

Each test calls a real app in process. The routes under test are added to it here: they report what
they see (the bound scope, the actor), so a binding that reaches only some handlers shows. The
tenant directory is a fake that records what it is asked, and the clock is a fixed clock the test
moves, so the 60 second record cache is tested at its edges.

The rules: the tenant is the signed claim; a request cannot name one (a header, a query, a body, the
host and a cookie are all ignored); an unknown, suspended or older-epoch tenant is refused with the
one 401 every other bad token gets; nothing is left bound after the request; a sync handler (run in
a thread pool) and an async one both see the binding; two requests in flight at once do not cross.
Sample identifiers only.
"""

import asyncio
import json
from collections.abc import Iterator
from datetime import timedelta
from typing import Annotated, Any

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.routing import APIRoute, _IncludedRouter
from httpx import ASGITransport, AsyncClient

from diucs.adapters.inbound.fhir_rest.app import create_app
from diucs.adapters.inbound.fhir_rest.auth import BFF_SECRET_NAME, current_actor, require_role
from diucs.adapters.inbound.fhir_rest.errors import LOGIN_TEXT
from diucs.adapters.inbound.fhir_rest.host_tenant import bind_host_tenant
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.tokens import TEST_BFF_SECRET, issue_test_token
from diucs.application.actor import Actor
from diucs.application.tenancy import current_scope_or_none
from diucs.domain.codes import Role
from diucs.domain.model.tenant import SuspendMode, SuspendReason, TenantStatus
from tests.support.edge import (
    EDGE_NOW,
    TENANT_A,
    TENANT_B,
    EdgeContainer,
    RecordingTenantDirectory,
    active_tenants,
)
from tests.support.tenant_samples import make_tenant

pytestmark = pytest.mark.asyncio(loop_scope="session")

PROBE = "/probe"
RECORD_CACHE_SECONDS = 60


def _scope_text() -> str | None:
    scope = current_scope_or_none()
    return None if scope is None else str(scope)


def build(
    directory: RecordingTenantDirectory, *, container: EdgeContainer | None = None
) -> FastAPI:
    container = container or EdgeContainer(tenants=directory)
    app = create_app(container)  # type: ignore[arg-type]
    app.state.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})
    app.state.edge_container = container

    @app.get(f"{PROBE}/async")
    async def probe_async(actor: Annotated[Actor, Depends(current_actor)]) -> dict[str, Any]:
        return {"scope": _scope_text(), "actor": actor.tenant_id, "role": actor.role.value}

    @app.get(f"{PROBE}/sync")
    def probe_sync(actor: Annotated[Actor, Depends(current_actor)]) -> dict[str, Any]:
        # A plain `def` runs in a thread pool: the binding must still be visible there.
        return {"scope": _scope_text(), "actor": actor.tenant_id}

    @app.post(f"{PROBE}/write")
    async def probe_write(
        request: Request, actor: Annotated[Actor, Depends(current_actor)]
    ) -> dict[str, Any]:
        return {"scope": _scope_text(), "body": (await request.body()).decode()}

    @app.get(f"{PROBE}/lead", dependencies=[Depends(require_role(Role.LEAD))])
    async def probe_lead() -> dict[str, Any]:
        return {"scope": _scope_text()}

    return app


def client_for(app: FastAPI, host: str = "test") -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url=f"http://{host}"
    )


def bearer(
    tenant: str = TENANT_A, role: Role = Role.ADVISOR, *, epoch: int = 1, sub: str = "prac-1"
) -> dict[str, str]:
    token = issue_test_token(role, [], sub, tenant=tenant, epoch=epoch)
    return {"Authorization": f"Bearer {token}"}


def json_bearer(*args: Any, **kwargs: Any) -> dict[str, str]:
    return {**bearer(*args, **kwargs), "Content-Type": "application/json"}


# ---------------------------------------------------------------- the binding


async def test_an_async_handler_runs_bound_to_the_tokens_tenant() -> None:
    app = build(active_tenants(TENANT_A))

    async with client_for(app) as client:
        response = await client.get(f"{PROBE}/async", headers=bearer(TENANT_A))

    assert response.status_code == 200
    assert response.json() == {"scope": TENANT_A, "actor": TENANT_A, "role": "advisor"}


async def test_a_sync_handler_in_the_thread_pool_runs_bound_to_the_tokens_tenant() -> None:
    app = build(active_tenants(TENANT_A))

    async with client_for(app) as client:
        response = await client.get(f"{PROBE}/sync", headers=bearer(TENANT_A))

    assert response.json() == {"scope": TENANT_A, "actor": TENANT_A}


async def test_a_role_dependency_binds_the_scope_too() -> None:
    app = build(active_tenants(TENANT_A))

    async with client_for(app) as client:
        response = await client.get(f"{PROBE}/lead", headers=bearer(TENANT_A, Role.LEAD))

    assert response.json() == {"scope": TENANT_A}


async def test_nothing_is_left_bound_after_the_request() -> None:
    # The reset trap: the test's own context is the request's context here, so a binding that was
    # set and not reset would still be there.
    app = build(active_tenants(TENANT_A))

    async with client_for(app) as client:
        await client.get(f"{PROBE}/async", headers=bearer(TENANT_A))
        await client.get(f"{PROBE}/sync", headers=bearer(TENANT_A))

    assert current_scope_or_none() is None


async def test_a_refused_request_leaves_nothing_bound() -> None:
    app = build(active_tenants(TENANT_A))

    async with client_for(app) as client:
        await client.get(f"{PROBE}/async", headers=bearer(TENANT_B))
        await client.get(f"{PROBE}/async")

    assert current_scope_or_none() is None


async def test_a_request_inside_another_binding_restores_that_binding() -> None:
    from diucs.application.tenancy import bind_tenant

    app = build(active_tenants(TENANT_A))

    with bind_tenant(TENANT_B):
        async with client_for(app) as client:
            response = await client.get(f"{PROBE}/async", headers=bearer(TENANT_A))
        assert _scope_text() == TENANT_B

    assert response.json()["scope"] == TENANT_A


async def test_the_request_binds_the_token_tenant_even_when_one_is_already_bound() -> None:
    from diucs.application.tenancy import bind_tenant

    app = build(active_tenants(TENANT_A, TENANT_B))

    with bind_tenant(TENANT_B):
        async with client_for(app) as client:
            response = await client.get(f"{PROBE}/async", headers=bearer(TENANT_A))

    assert response.json()["scope"] == TENANT_A


async def test_two_requests_in_flight_at_once_keep_their_own_tenant() -> None:
    app = build(active_tenants(TENANT_A, TENANT_B))
    arrived = 0
    both_in = asyncio.Event()

    @app.get(f"{PROBE}/rendezvous", dependencies=[Depends(current_actor)])
    async def rendezvous() -> dict[str, Any]:
        nonlocal arrived
        arrived += 1
        if arrived == 2:
            both_in.set()
        await asyncio.wait_for(both_in.wait(), timeout=5)
        await asyncio.sleep(0)
        return {"scope": _scope_text()}

    async with client_for(app) as client:
        first, second = await asyncio.gather(
            client.get(f"{PROBE}/rendezvous", headers=bearer(TENANT_A)),
            client.get(f"{PROBE}/rendezvous", headers=bearer(TENANT_B)),
        )

    assert first.json() == {"scope": TENANT_A}
    assert second.json() == {"scope": TENANT_B}


# ---------------------------------------------------------------- the tenant is never request input


async def test_a_request_cannot_name_a_tenant() -> None:
    app = build(active_tenants(TENANT_A, TENANT_B))
    headers = {
        **bearer(TENANT_A),
        "X-Tenant": TENANT_B,
        "X-Tenant-Id": TENANT_B,
        "X-Forwarded-Host": f"{TENANT_B}.example.test",
        "Cookie": f"tenant={TENANT_B}; tenantId={TENANT_B}",
        "Forwarded": f"host={TENANT_B}.example.test",
    }

    async with client_for(app, host=f"{TENANT_B}.example.test") as client:
        response = await client.get(
            f"{PROBE}/async", headers=headers, params={"tenant": TENANT_B, "tenantId": TENANT_B}
        )

    assert response.status_code == 200
    assert response.json()["scope"] == TENANT_A
    assert response.json()["actor"] == TENANT_A


async def test_a_body_that_names_a_tenant_changes_nothing() -> None:
    app = build(active_tenants(TENANT_A, TENANT_B))
    body = json.dumps({"tenant": TENANT_B, "tenantId": TENANT_B, "tenant_id": TENANT_B})

    async with client_for(app) as client:
        response = await client.post(f"{PROBE}/write", headers=json_bearer(TENANT_A), content=body)

    assert response.json()["scope"] == TENANT_A


async def test_the_directory_is_asked_about_the_claimed_tenant_only() -> None:
    directory = active_tenants(TENANT_A, TENANT_B)
    app = build(directory)

    async with client_for(app) as client:
        await client.get(
            f"{PROBE}/async",
            headers={**bearer(TENANT_A), "X-Tenant": TENANT_B},
            params={"tenant": TENANT_B},
        )

    assert directory.asked == [TENANT_A]


# ---------------------------------------------------------------- refusals are one 401


async def _refused(app: FastAPI, headers: dict[str, str]) -> Any:
    async with client_for(app) as client:
        return await client.get(f"{PROBE}/async", headers=headers)


async def test_the_causes_of_a_refusal_all_answer_with_the_same_401() -> None:
    suspended = make_tenant(
        TenantStatus.SUSPENDED,
        id=TENANT_B,
        epoch=2,
        suspend_mode=SuspendMode.BLOCKED,
        suspend_reason=SuspendReason.SECURITY_INCIDENT,
        suspended_at=EDGE_NOW - timedelta(days=1),
    )
    directory = RecordingTenantDirectory(make_tenant(id=TENANT_A, epoch=3), suspended)
    app = build(directory)
    tampered = bearer(TENANT_A)["Authorization"][:-3] + "AAA"

    answers = [
        await _refused(app, {}),  # no token
        await _refused(app, {"Authorization": tampered}),  # bad signature
        await _refused(app, bearer("tenant-zz")),  # a tenant with no record
        await _refused(app, bearer(TENANT_A, epoch=1)),  # an epoch that has moved on
        await _refused(app, bearer(TENANT_B, epoch=2)),  # a blocked suspension
        await _refused(app, bearer(TENANT_A, Role.PLATFORM_OPERATOR, epoch=3)),  # no data access
    ]

    assert {response.status_code for response in answers} == {401}
    assert len({response.content for response in answers}) == 1
    assert len({response.headers["www-authenticate"] for response in answers}) == 1
    assert LOGIN_TEXT in answers[0].text


async def test_an_unknown_tenant_is_refused() -> None:
    app = build(active_tenants(TENANT_A))

    response = await _refused(app, bearer(TENANT_B))

    assert response.status_code == 401


async def test_a_suspended_tenant_in_blocked_mode_is_refused_for_every_role() -> None:
    blocked = make_tenant(
        TenantStatus.SUSPENDED,
        id=TENANT_A,
        epoch=2,
        suspend_mode=SuspendMode.BLOCKED,
        suspend_reason=SuspendReason.SECURITY_INCIDENT,
        suspended_at=EDGE_NOW,
    )
    app = build(RecordingTenantDirectory(blocked))

    for role in (Role.TENANT_ADMIN, Role.LEAD, Role.ADVISOR, Role.WALL):
        assert (await _refused(app, bearer(TENANT_A, role, epoch=2))).status_code == 401


async def test_a_read_only_suspension_lets_only_the_tenant_admin_read() -> None:
    read_only = make_tenant(
        TenantStatus.SUSPENDED,
        id=TENANT_A,
        epoch=2,
        suspend_mode=SuspendMode.READ_ONLY,
        suspend_reason=SuspendReason.CONTRACT,
        suspended_at=EDGE_NOW,
    )
    app = build(RecordingTenantDirectory(read_only))

    async with client_for(app) as client:
        admin_read = await client.get(
            f"{PROBE}/async", headers=bearer(TENANT_A, Role.TENANT_ADMIN, epoch=2)
        )
        admin_write = await client.post(
            f"{PROBE}/write",
            headers=json_bearer(TENANT_A, Role.TENANT_ADMIN, epoch=2),
            content="{}",
        )
        lead_read = await client.get(f"{PROBE}/async", headers=bearer(TENANT_A, Role.LEAD, epoch=2))

    assert admin_read.status_code == 200
    assert admin_read.json()["scope"] == TENANT_A
    assert admin_write.status_code == 401
    assert lead_read.status_code == 401


async def test_the_operator_role_never_reaches_a_data_route() -> None:
    app = build(active_tenants(TENANT_A))

    response = await _refused(app, bearer(TENANT_A, Role.PLATFORM_OPERATOR))

    assert response.status_code == 401


async def test_the_directory_is_not_asked_when_the_token_is_bad() -> None:
    directory = active_tenants(TENANT_A)
    app = build(directory)
    expired = issue_test_token(
        Role.ADVISOR, [], "prac-1", tenant=TENANT_A, expires_at=EDGE_NOW - timedelta(seconds=1)
    )

    await _refused(app, {})
    await _refused(app, {"Authorization": "Bearer not-a-token"})
    await _refused(app, {"Authorization": f"Bearer {expired}"})
    await _refused(app, {"Authorization": f"Basic {expired}"})

    assert directory.asked == []


async def test_a_directory_that_fails_fails_closed_and_runs_no_handler() -> None:
    directory = RecordingTenantDirectory()
    directory.put(RuntimeError("the directory is down"), TENANT_A)
    app = build(directory)
    ran = False

    @app.get(f"{PROBE}/never", dependencies=[Depends(current_actor)])
    async def never() -> dict[str, Any]:
        nonlocal ran
        ran = True
        return {}

    async with client_for(app) as client:
        response = await client.get(f"{PROBE}/never", headers=bearer(TENANT_A))

    assert response.status_code == 500
    assert ran is False
    assert "directory is down" not in response.text
    assert current_scope_or_none() is None


async def test_a_record_for_another_tenant_than_the_claim_is_refused() -> None:
    directory = RecordingTenantDirectory()
    directory.put(make_tenant(id=TENANT_B), TENANT_A)  # a directory that answers wrongly
    app = build(directory)

    response = await _refused(app, bearer(TENANT_A))

    assert response.status_code == 401


# ---------------------------------------------------------------- the epoch (H-T23)


async def test_a_token_from_before_a_suspend_and_resume_is_refused() -> None:
    directory = RecordingTenantDirectory(make_tenant(id=TENANT_A, epoch=3))
    app = build(directory)

    response = await _refused(app, bearer(TENANT_A, epoch=2))

    assert response.status_code == 401


async def test_a_token_newer_than_the_cached_record_reads_the_record_again_once() -> None:
    directory = active_tenants(TENANT_A, epoch=1)
    app = build(directory)
    async with client_for(app) as client:
        assert (await client.get(f"{PROBE}/async", headers=bearer(epoch=1))).status_code == 200
        directory.put(make_tenant(id=TENANT_A, epoch=2))  # a resume the cache has not seen

        response = await client.get(f"{PROBE}/async", headers=bearer(epoch=2))

    assert response.status_code == 200
    assert directory.asked == [TENANT_A, TENANT_A]


async def test_a_token_newer_than_a_fresh_record_is_refused_after_one_more_read() -> None:
    directory = active_tenants(TENANT_A, epoch=1)
    app = build(directory)

    response = await _refused(app, bearer(TENANT_A, epoch=5))

    assert response.status_code == 401
    assert directory.asked == [TENANT_A]  # a first read is already fresh: no second one


async def test_a_token_newer_than_a_cached_record_is_refused_when_the_record_is_still_behind() -> (
    None
):
    directory = active_tenants(TENANT_A, epoch=1)
    app = build(directory)
    async with client_for(app) as client:
        await client.get(f"{PROBE}/async", headers=bearer(epoch=1))
        response = await client.get(f"{PROBE}/async", headers=bearer(epoch=5))

    assert response.status_code == 401
    assert directory.asked == [TENANT_A, TENANT_A]


# ---------------------------------------------------------------- the record cache


async def test_the_record_is_cached_for_less_than_a_minute() -> None:
    directory = active_tenants(TENANT_A)
    container = EdgeContainer(tenants=directory)
    app = build(directory, container=container)
    async with client_for(app) as client:
        await client.get(f"{PROBE}/async", headers=bearer())
        container.clock.advance(timedelta(seconds=RECORD_CACHE_SECONDS - 1))
        await client.get(f"{PROBE}/async", headers=bearer())

    assert directory.asked == [TENANT_A]


async def test_a_suspend_takes_effect_when_the_cached_record_is_a_minute_old() -> None:
    directory = active_tenants(TENANT_A)
    container = EdgeContainer(tenants=directory)
    app = build(directory, container=container)
    blocked = make_tenant(
        TenantStatus.SUSPENDED,
        id=TENANT_A,
        epoch=2,
        suspend_mode=SuspendMode.BLOCKED,
        suspend_reason=SuspendReason.SECURITY_INCIDENT,
        suspended_at=EDGE_NOW,
    )
    async with client_for(app) as client:
        before = await client.get(f"{PROBE}/async", headers=bearer(epoch=1))
        directory.put(blocked)
        container.clock.advance(timedelta(seconds=RECORD_CACHE_SECONDS - 1))
        still_cached = await client.get(f"{PROBE}/async", headers=bearer(epoch=1))
        container.clock.advance(timedelta(seconds=1))
        after = await client.get(f"{PROBE}/async", headers=bearer(epoch=1))

    assert (before.status_code, still_cached.status_code, after.status_code) == (200, 200, 401)


async def test_the_cache_is_per_tenant() -> None:
    directory = active_tenants(TENANT_A, TENANT_B)
    app = build(directory)
    async with client_for(app) as client:
        a = await client.get(f"{PROBE}/async", headers=bearer(TENANT_A))
        b = await client.get(f"{PROBE}/async", headers=bearer(TENANT_B))

    assert a.json()["scope"] == TENANT_A
    assert b.json()["scope"] == TENANT_B
    assert directory.asked == [TENANT_A, TENANT_B]


async def test_an_unknown_tenant_is_not_cached() -> None:
    directory = RecordingTenantDirectory()
    app = build(directory)
    async with client_for(app) as client:
        first = await client.get(f"{PROBE}/async", headers=bearer(TENANT_A))
        directory.put(make_tenant(id=TENANT_A))
        second = await client.get(f"{PROBE}/async", headers=bearer(TENANT_A))

    assert (first.status_code, second.status_code) == (401, 200)


# ---------------------------------------------------------------- the route registry


# Every route either binds the scope through the actor dependency, or is on this list with the
# reason it needs no token. A route added without either fails the test below.
TENANT_FREE = {
    ("GET", "/health"): "no data, no tenant",
    ("GET", "/fhir/metadata"): "the capability statement names no tenant data",
    ("PUT", "/fhir/Observation/{report_id}"): "refuses every write with 405, reads nothing (R04)",
    ("PATCH", "/fhir/Observation/{report_id}"): "refuses every write with 405, reads nothing (R04)",
    (
        "DELETE",
        "/fhir/Observation/{report_id}",
    ): "refuses every write with 405, reads nothing (R04)",
}
BINDS_ITSELF = {
    ("GET", "/public/tenant-profile"): "tenant from the host, by bind_host_tenant (TEN-040)",
    ("POST", "/screens/pairing"): "tenant from the host (R15)",
    ("GET", "/screens/pairing/{pairing_id}"): "tenant from the host (R15)",
    ("POST", "/identity/code"): "tenant from the host (R11)",
    ("POST", "/identity/code/verify"): "tenant from the host (R11)",
    ("POST", "/identity/pin"): "tenant from the host (R11)",
    ("POST", "/identity/pin/verify"): "tenant from the host (R11)",
    ("POST", "/identity/new-phone"): "tenant from the host, the code edge of R11 (R13, DEC-411)",
    ("POST", "/identity/new-phone/verify"): "tenant from the host, the code edge of R11 (R13)",
    ("GET", "/identity/status"): "tenant from the host (R11)",
    ("POST", "/webhooks/sms/twilio"): "tenant from the number called and the account (I07)",
    ("POST", "/webhooks/sms/twilio/status"): "tenant from the account and the message (I07)",
    ("GET", "/links/{token}"): "tenant from the link token record (L01)",
    ("POST", "/links/{token}"): "tenant from the link token record (L01)",
    ("POST", "/links/{token}/renew"): "tenant from the link token record (L01)",
    ("POST", "/test/synthetic/prompt"): "the synthetic hook's own configured tenant (O09)",
}


def _depends_on(dependant: Any, target: Any) -> bool:
    if dependant.call is target:
        return True
    return any(_depends_on(child, target) for child in dependant.dependencies)


def _depends_on_actor(dependant: Any) -> bool:
    if dependant.call is current_actor:
        return True
    return any(_depends_on_actor(child) for child in dependant.dependencies)


def _effective_routes(routes: Any) -> Iterator[Any]:
    """Every route of the app with its full path and dependencies. FastAPI includes a router
    lazily (`_IncludedRouter`, whose `effective_candidates` carry the prefix and the router's
    dependencies), so the walk uses those. The lock file pins FastAPI; a shape this walk does not
    know fails the test instead of passing it by missing a route."""
    for route in routes:
        if isinstance(route, APIRoute) or hasattr(route, "dependant") and route.dependant:
            yield route
        elif isinstance(route, _IncludedRouter):
            yield from _effective_routes(route.effective_candidates())
            yield from _effective_routes(route.effective_low_priority_routes())
        else:
            raise AssertionError(f"a route of a kind the registry test does not know: {route!r}")


def _routes(app: FastAPI) -> dict[tuple[str, str], Any]:
    found: dict[tuple[str, str], Any] = {}
    for route in _effective_routes(app.routes):
        for method in route.methods - {"HEAD", "OPTIONS"}:
            found[(method, route.path)] = route
    return found


async def test_every_route_binds_the_scope_or_is_on_the_reviewed_list() -> None:
    app = build(active_tenants(TENANT_A))
    exempt = set(TENANT_FREE) | set(BINDS_ITSELF)

    unbound = {
        key
        for key, route in _routes(app).items()
        if not key[1].startswith(PROBE) and not _depends_on_actor(route.dependant)
    }

    assert unbound == exempt


async def test_no_listed_route_is_missing_from_the_app() -> None:
    # A stale entry hides a removed route: each listed route still exists.
    app = build(active_tenants(TENANT_A))

    missing = (set(TENANT_FREE) | set(BINDS_ITSELF)) - set(_routes(app))

    assert missing == set()


async def test_the_listed_routes_do_not_take_the_actor_dependency() -> None:
    # A route on the list that also depends on the actor does not need its place there.
    app = build(active_tenants(TENANT_A))

    listed = {key for key in _routes(app) if key in TENANT_FREE or key in BINDS_ITSELF}

    assert all(not _depends_on_actor(_routes(app)[key].dependant) for key in listed)


# ---------------------------------------------------------------- the stream and the real routes


async def test_the_live_stream_subscribes_in_the_tokens_tenant() -> None:
    seen: list[str | None] = []

    class Cache:
        async def subscribe(self, channel: str) -> Any:
            seen.append(_scope_text())

            async def messages() -> Any:
                yield '{"serviceId":"svc-1","kind":"capacity","changedAt":"2026-10-23T13:12:00Z"}'

            return messages()

    app = build(active_tenants(TENANT_A, TENANT_B))
    app.state.cache = Cache()

    async with client_for(app) as client:
        response = await client.get("/events", headers=bearer(TENANT_A, Role.ADVISOR))

    assert response.status_code == 200
    assert "event: board" in response.text
    assert seen == [TENANT_A]


async def test_the_live_stream_refuses_a_token_for_a_tenant_with_no_record() -> None:
    app = build(active_tenants(TENANT_B))
    app.state.cache = object()

    async with client_for(app) as client:
        response = await client.get("/events", headers=bearer(TENANT_A, Role.ADVISOR))

    assert response.status_code == 401


async def test_every_public_route_binds_the_tenant_of_its_host_through_the_one_binder() -> None:
    app = build(active_tenants(TENANT_A))

    public = {key: route for key, route in _routes(app).items() if key[1].startswith("/public/")}

    assert public
    for key, route in public.items():
        assert _depends_on(route.dependant, bind_host_tenant), key
        assert not _depends_on_actor(route.dependant), key
