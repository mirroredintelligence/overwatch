"""The network and grant administration API (TEN-079, DEC-132 items 2 and 3, DEC-136 items 3 and
10, DEC-134 item 4).

Three kinds of test, none of which needs a store for the first two:

1. **The role matrix.** Every route against all thirteen roles. The roles a route names get its
   success status, the platform operator is refused at the edge (401: it has no data access), and
   every other role gets the one 404 and never reaches a use case.
2. **Two tenants.** The real use cases over the registry fake, behind the real edge: an organisation
   reads and changes only what is its own, another's grant, membership or listing is the same 404
   as a missing one and changes nothing, the owner's administrator sees the whole network by the
   organisations' names, and no body names a tenant, an account or a person. A body or a query that
   names a tenant is refused or ignored.
3. **A whole flow** on the real graph, through HTTP, from the invitation to the end of a grant.
"""

import os
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from neo4j import AsyncDriver

from diucs.adapters.inbound.fhir_rest.app import create_app
from diucs.adapters.inbound.fhir_rest.auth import BFF_SECRET_NAME
from diucs.adapters.inbound.fhir_rest.routes_network_admin import (
    NETWORK_ID_PATTERN,
    RECORD_ID_PATTERN,
    NetworkAdminServices,
)
from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.tokens import TEST_BFF_SECRET, issue_test_token
from diucs.application.use_cases.grants import (
    ApproveGrant,
    DeclineGrant,
    EndGrant,
    ProposeGrant,
    QueryGrants,
    ReviseGrant,
)
from diucs.application.use_cases.listing_admission import (
    DecideListing,
    QueryListings,
    RequestListing,
)
from diucs.application.use_cases.membership import (
    AcceptMembership,
    InviteMember,
    LeaveNetwork,
    RemoveMember,
)
from diucs.application.use_cases.network_admin import (
    GovernanceRecorder,
    QueryNetworkAdmin,
    RecordAgreement,
)
from diucs.application.use_cases.network_leave import EndResult
from diucs.domain.codes import Role
from diucs.domain.model.network import GrantScope
from tests.support.edge import EdgeContainer, active_tenants
from tests.support.network_admin_fakes import (
    Ids,
    MemoryDirectory,
    MemoryRegistry,
    UnitFactories,
    UnitWorld,
    active_tenant,
    staff_ref,
)
from tests.support.network_admin_rig import AdminRig
from tests.support.network_samples import (
    MEMBER_B,
    MEMBER_C,
    NETWORK_ID,
    OWNER,
    make_grant,
    make_listing,
    make_member,
    make_network,
    make_owner_membership,
    rid,
)
from tests.support.network_world import world_ids
from tests.support.projection_samples import SERVICE_ID, sample_profile
from tests.support.tenancy import RunIdentity

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 10, 30, 10, 0, tzinfo=UTC)
NET = "net-sample"
REC = "rec-1"
ALL_ROLES = tuple(Role)
OP = Role.PLATFORM_OPERATOR
TA, NA, LD = Role.TENANT_ADMIN, Role.NETWORK_ADMIN, Role.LEAD

# (method, path, body, the roles that may use it, the status they get)
ROUTES: tuple[tuple[str, str, dict[str, Any] | None, frozenset[Role], int], ...] = (
    ("GET", "/network-admin/networks", None, frozenset({TA, NA}), 200),
    ("GET", f"/network-admin/network/{NET}/members", None, frozenset({NA}), 200),
    ("POST", f"/network-admin/network/{NET}/members", {"tenant_id": "org-x"}, frozenset({NA}), 201),
    ("POST", f"/network-admin/network/{NET}/members/{REC}/remove", None, frozenset({NA}), 200),
    ("POST", f"/network-admin/network/{NET}/leave", None, frozenset({TA}), 200),
    (
        "POST",
        f"/network-admin/memberships/{REC}/accept",
        {"agreement_version": 1},
        frozenset({TA}),
        200,
    ),
    (
        "POST",
        f"/network-admin/network/{NET}/agreement",
        {"reference": "DSA-2", "version": 2},
        frozenset({NA}),
        200,
    ),
    ("GET", f"/network-admin/network/{NET}/projection", None, frozenset({NA}), 200),
    ("GET", "/network-admin/grants", None, frozenset({TA}), 200),
    ("GET", f"/network-admin/network/{NET}/grants", None, frozenset({NA}), 200),
    (
        "POST",
        "/network-admin/grants",
        {"network_id": NET, "scope": "capacity"},
        frozenset({TA}),
        201,
    ),
    ("POST", f"/network-admin/grants/{REC}/approve", None, frozenset({TA, NA}), 200),
    ("POST", f"/network-admin/grants/{REC}/decline", None, frozenset({TA, NA}), 200),
    ("POST", f"/network-admin/grants/{REC}/end", None, frozenset({TA}), 200),
    ("POST", f"/network-admin/grants/{REC}/revise", {}, frozenset({TA}), 201),
    ("GET", f"/network-admin/network/{NET}/listings", None, frozenset({NA}), 200),
    ("GET", f"/network-admin/network/{NET}/listings/mine", None, frozenset({TA, LD}), 200),
    (
        "POST",
        f"/network-admin/network/{NET}/listings",
        {"service_id": "svc-1"},
        frozenset({TA, LD}),
        201,
    ),
    ("POST", f"/network-admin/network/{NET}/listings/{REC}/admit", None, frozenset({NA}), 200),
    ("POST", f"/network-admin/network/{NET}/listings/{REC}/reinstate", None, frozenset({NA}), 200),
    (
        "POST",
        f"/network-admin/network/{NET}/listings/{REC}/decline",
        {"reason": "outside-area"},
        frozenset({NA}),
        200,
    ),
    (
        "POST",
        f"/network-admin/network/{NET}/listings/{REC}/suspend",
        {"reason": "data-quality"},
        frozenset({NA}),
        200,
    ),
    (
        "POST",
        f"/network-admin/network/{NET}/listings/{REC}/withdraw",
        None,
        frozenset({TA, LD}),
        200,
    ),
)


# ---------------------------------------------------------------- 1. the role matrix


class _Stub:
    """A use case that answers with what a route reads of its result, and records that it ran."""

    def __init__(self, name: str, calls: list[str], answer: Any = None) -> None:
        self._name = name
        self._calls = calls
        self._answer = answer

    async def _run(self, *args: Any, **kw: Any) -> Any:
        self._calls.append(self._name)
        return self._answer

    def __getattr__(self, method: str) -> Callable[..., Awaitable[Any]]:
        if method.startswith("_"):
            raise AttributeError(method)
        return self._run


@dataclass
class _Result:
    membership_id: str = "mem-1"
    effective: bool = True
    grants_lapsed: int = 0
    listings_withdrawn: int = 0


def _stub_services(calls: list[str]) -> NetworkAdminServices:
    def make(name: str, answer: Any = None) -> Any:
        stub = _Stub(name, calls, answer)

        async def execute(*a: Any, **k: Any) -> Any:
            return await stub._run()

        stub.execute = execute  # type: ignore[attr-defined]
        return stub

    class _Query(_Stub):
        async def networks(self, *a: Any) -> list[Any]:
            self._calls.append("networks")
            return []

        async def members(self, *a: Any) -> list[Any]:
            self._calls.append("members")
            return []

        async def projection_status(self, *a: Any) -> list[Any]:
            self._calls.append("projection")
            return []

    class _Grants(_Stub):
        async def for_tenant(self, *a: Any) -> list[Any]:
            self._calls.append("for_tenant")
            return []

        async def for_network(self, *a: Any) -> list[Any]:
            self._calls.append("for_network")
            return []

    class _Listings(_Stub):
        async def for_network(self, *a: Any) -> list[Any]:
            self._calls.append("listings")
            return []

        async def of_member(self, *a: Any) -> list[Any]:
            self._calls.append("mine")
            return []

    return NetworkAdminServices(
        query=_Query("query", calls),  # type: ignore[arg-type]
        invite=make("invite", _Result()),
        accept=make("accept"),
        leave=make("leave", _Result()),
        remove=make("remove", _Result()),
        agreement=make("agreement"),
        grants=_Grants("grants", calls),  # type: ignore[arg-type]
        propose=make("propose", "grant-1"),
        approve=make("approve", _Result()),
        decline=make("decline"),
        end=make("end"),
        revise=make("revise", "grant-2"),
        listings=_Listings("listings", calls),  # type: ignore[arg-type]
        request_listing=make("request_listing", "lst-1"),
        decide_listing=make("decide_listing"),
    )


def _bearer(role: Role, tenant: str, who: str = "admin", **kw: Any) -> dict[str, str]:
    token = issue_test_token(
        role,
        [],
        staff_ref(f"{tenant}/{who}"),
        tenant=tenant,
        expires_at=NOW + timedelta(hours=1),
        **kw,
    )
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _app(
    tenants: tuple[str, ...], services: NetworkAdminServices | None, clock: FixedClock | None = None
) -> FastAPI:
    container = EdgeContainer(tenants=active_tenants(*tenants), clock=clock or FixedClock(NOW))
    app: FastAPI = create_app(container)  # type: ignore[arg-type]
    app.state.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})
    if services is not None:
        app.state.network_admin = services
    return app


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    )


def _ids() -> list[tuple[str, str, dict[str, Any] | None, frozenset[Role], int]]:
    return list(ROUTES)


@pytest.mark.parametrize(("method", "path", "body", "allowed", "status"), ROUTES)
async def test_every_route_against_all_thirteen_roles(
    method: str, path: str, body: dict[str, Any] | None, allowed: frozenset[Role], status: int
) -> None:
    assert len(ALL_ROLES) == 13
    calls: list[str] = []
    app = _app(("org-a",), _stub_services(calls))
    async with _client(app) as client:
        for role in ALL_ROLES:
            calls.clear()
            response = await client.request(method, path, json=body, headers=_bearer(role, "org-a"))
            if role in allowed:
                assert response.status_code == status, (role, response.text)
                assert len(calls) == 1
            elif role is OP:
                assert response.status_code == 401, (role, response.text)  # no data access
                assert calls == []
            else:
                assert response.status_code == 404, (role, response.text)
                assert calls == []  # a refused role never reaches a use case


@pytest.mark.parametrize(("method", "path", "body", "allowed", "status"), ROUTES)
async def test_no_token_is_a_401_and_never_reaches_a_use_case(
    method: str, path: str, body: dict[str, Any] | None, allowed: frozenset[Role], status: int
) -> None:
    calls: list[str] = []
    async with _client(_app(("org-a",), _stub_services(calls))) as client:
        response = await client.request(
            method, path, json=body, headers={"Content-Type": "application/json"}
        )
    assert response.status_code == 401 and calls == []


async def test_a_token_for_a_tenant_the_directory_does_not_list_is_refused_at_the_edge() -> None:
    calls: list[str] = []
    async with _client(_app(("org-a",), _stub_services(calls))) as client:
        response = await client.get("/network-admin/networks", headers=_bearer(NA, "org-z"))
    assert response.status_code == 401 and calls == []


async def test_a_token_whose_claims_are_tampered_is_refused() -> None:
    calls: list[str] = []
    headers = _bearer(NA, "org-a")
    token = headers["Authorization"].split(" ")[1]
    forged = token[:-3] + ("AAA" if not token.endswith("AAA") else "BBB")
    async with _client(_app(("org-a",), _stub_services(calls))) as client:
        response = await client.get(
            "/network-admin/networks", headers={"Authorization": f"Bearer {forged}"}
        )
    assert response.status_code == 401 and calls == []


async def test_without_services_wired_the_routes_fail_closed() -> None:
    async with _client(_app(("org-a",), None)) as client:
        response = await client.get("/network-admin/networks", headers=_bearer(NA, "org-a"))
    assert response.status_code == 500


@pytest.mark.parametrize(
    "path",
    [
        "/network-admin/network/not-a-network/members",
        "/network-admin/network/NET-UPPER/members",
        f"/network-admin/network/{NET}/members/has space/remove",
        "/network-admin/grants/%2e%2e/approve",
    ],
)
async def test_an_id_that_is_not_the_domains_shape_never_reaches_a_use_case(path: str) -> None:
    calls: list[str] = []
    method = "POST" if path.endswith(("remove", "approve")) else "GET"
    async with _client(_app(("org-a",), _stub_services(calls))) as client:
        response = await client.request(method, path, headers=_bearer(NA, "org-a"))
    assert response.status_code in (400, 404, 422) and calls == []


async def test_the_path_patterns_are_the_domains() -> None:
    from diucs.domain.model.network import NETWORK_ID_PATTERN as DOMAIN_NETWORK
    from diucs.domain.model.network import RECORD_ID_PATTERN as DOMAIN_RECORD

    assert f"^{DOMAIN_NETWORK.pattern}$" == NETWORK_ID_PATTERN
    assert f"^{DOMAIN_RECORD.pattern}$" == RECORD_ID_PATTERN


@pytest.mark.parametrize(
    ("path", "body"),
    [
        (f"/network-admin/network/{NET}/members", {"tenant_id": "org-x", "extra": 1}),
        (f"/network-admin/network/{NET}/members", {}),
        (f"/network-admin/memberships/{REC}/accept", {"agreement_version": "1"}),
        (f"/network-admin/network/{NET}/agreement", {"reference": "x", "version": 1.5}),
        ("/network-admin/grants", {"network_id": NET, "scope": "capacity", "tenant": "org-b"}),
        ("/network-admin/grants", {"network_id": NET, "scope": "everything"}),
        (
            "/network-admin/grants",
            {"network_id": NET, "scope": "capacity", "effective_from": "soon"},
        ),
        (f"/network-admin/network/{NET}/listings", {"service_id": "svc-1", "network": NET}),
        (f"/network-admin/network/{NET}/listings/{REC}/decline", {"reason": "because"}),
    ],
)
async def test_a_body_with_an_unknown_field_or_a_wrong_type_is_a_400_and_runs_nothing(
    path: str, body: dict[str, Any]
) -> None:
    calls: list[str] = []
    role = LD if path.endswith("listings") else NA
    role = TA if "/grants" in path or "accept" in path else role
    async with _client(_app(("org-a",), _stub_services(calls))) as client:
        response = await client.post(path, json=body, headers=_bearer(role, "org-a"))
    assert response.status_code in (400, 422), response.text
    assert calls == []


async def test_every_answer_is_never_cached() -> None:
    calls: list[str] = []
    async with _client(_app(("org-a",), _stub_services(calls))) as client:
        for method, path, body, allowed, _ in ROUTES:
            role = sorted(allowed, key=lambda r: r.value)[0]
            response = await client.request(method, path, json=body, headers=_bearer(role, "org-a"))
            assert response.headers["cache-control"] == "no-store", path


# ---------------------------------------------------------------- 2. two tenants


class _World:
    """The real use cases over the registry fake, behind the real edge."""

    def __init__(self) -> None:
        self.log: list[str] = []
        self.world = UnitWorld(self.log)
        self.registry = MemoryRegistry(self.log)
        self.registry.seed(
            make_network(),
            members=[
                make_owner_membership(),
                make_member(MEMBER_B, id=rid("mem-opaque-b")),
                make_member(MEMBER_C, id=rid("mem-opaque-c")),
            ],
        )
        self.world.services[(MEMBER_B, SERVICE_ID)] = sample_profile()
        self.world.services[(MEMBER_C, SERVICE_ID)] = sample_profile()
        self.directory = directory = MemoryDirectory(
            active_tenant(OWNER, "Owner Org"),
            active_tenant(MEMBER_B, "Member B Org"),
            active_tenant(MEMBER_C, "Member C Org"),
        )
        self.clock = FixedClock(NOW)
        factories = UnitFactories(self.world)
        recorder = GovernanceRecorder(
            factories.tenant,  # type: ignore[arg-type]
            factories.network,  # type: ignore[arg-type]
            Ids("ob"),
            self.clock,
        )

        class _Ends:
            async def end_grant(self, *a: Any, **k: Any) -> EndResult:
                return EndResult(1, 1)

            async def end_member(self, *a: Any, **k: Any) -> EndResult:
                return EndResult(1, 1)

        reg: Any = self.registry
        ends: Any = _Ends()
        self.services = NetworkAdminServices(
            query=QueryNetworkAdmin(reg, directory, factories.network_read_only),  # type: ignore[arg-type]
            invite=InviteMember(reg, directory, recorder, Ids("mem"), self.clock),  # type: ignore[arg-type]
            accept=AcceptMembership(reg, recorder, self.clock),
            leave=LeaveNetwork(reg, ends, recorder, self.clock),
            remove=RemoveMember(reg, ends, recorder, self.clock),
            agreement=RecordAgreement(reg, recorder, self.clock),
            grants=QueryGrants(reg, directory, self.clock),  # type: ignore[arg-type]
            propose=ProposeGrant(reg, recorder, Ids("grant"), self.clock),
            approve=ApproveGrant(reg, recorder, self.clock),
            decline=DeclineGrant(reg, recorder, self.clock),
            end=EndGrant(reg, ends, recorder, self.clock),
            revise=ReviseGrant(reg, recorder, Ids("rev"), self.clock),
            listings=QueryListings(reg, directory),  # type: ignore[arg-type]
            request_listing=RequestListing(
                reg,
                factories.tenant_read_only,
                recorder,
                Ids("lst"),
                self.clock,  # type: ignore[arg-type]
            ),
            decide_listing=DecideListing(reg, recorder, self.clock),
        )
        self.app = _app((OWNER, MEMBER_B, MEMBER_C), self.services, self.clock)

    def seed_grants(self) -> tuple[str, str]:
        b = make_grant(id=rid("grant-b"), tenant=MEMBER_B)
        c = make_grant(id=rid("grant-c"), tenant=MEMBER_C)
        self.registry.grant_rows[b.id] = b
        self.registry.grant_rows[c.id] = c
        return b.id, c.id


@pytest.fixture
def two() -> _World:
    return _World()


async def test_an_organisation_reads_only_its_own_grants_and_the_owner_reads_every_one(
    two: _World,
) -> None:
    two.seed_grants()
    async with _client(two.app) as client:
        mine = await client.get("/network-admin/grants", headers=_bearer(TA, MEMBER_B))
        every = await client.get(
            f"/network-admin/network/{NETWORK_ID}/grants", headers=_bearer(NA, OWNER)
        )
    assert {g["organisation_name"] for g in mine.json()["grants"]} == {"Member B Org"}
    assert {g["organisation_name"] for g in every.json()["grants"]} == {
        "Member B Org",
        "Member C Org",
    }
    assert all(g["effective"] is True for g in every.json()["grants"])


async def test_another_organisations_grant_is_the_same_404_as_a_missing_one_and_changes_nothing(
    two: _World,
) -> None:
    _, other = two.seed_grants()
    headers = _bearer(TA, MEMBER_B)
    async with _client(two.app) as client:
        for action in ("approve", "decline", "end", "revise"):
            body = {} if action == "revise" else None
            foreign = await client.post(
                f"/network-admin/grants/{other}/{action}", json=body, headers=headers
            )
            missing = await client.post(
                f"/network-admin/grants/grant-none/{action}", json=body, headers=headers
            )
            assert (foreign.status_code, foreign.text) == (missing.status_code, missing.text), (
                action
            )
            assert foreign.status_code == 404
    assert two.registry.grant_rows[other].status.value == "approved"
    assert two.world.outbox == []


async def test_the_owner_cannot_end_a_members_grant_and_a_member_cannot_see_the_owners_views(
    two: _World,
) -> None:
    b, _ = two.seed_grants()
    async with _client(two.app) as client:
        ended = await client.post(f"/network-admin/grants/{b}/end", headers=_bearer(NA, OWNER))
        members = await client.get(
            f"/network-admin/network/{NETWORK_ID}/members", headers=_bearer(NA, MEMBER_B)
        )
        listings = await client.get(
            f"/network-admin/network/{NETWORK_ID}/listings", headers=_bearer(NA, MEMBER_B)
        )
    assert ended.status_code == 404 and members.status_code == 404 and listings.status_code == 404


async def test_the_owner_lists_the_members_by_name_with_the_membership_as_the_handle(
    two: _World,
) -> None:
    async with _client(two.app) as client:
        response = await client.get(
            f"/network-admin/network/{NETWORK_ID}/members", headers=_bearer(NA, OWNER)
        )
    rows = response.json()["members"]
    assert {r["organisation_name"] for r in rows} == {"Owner Org", "Member B Org", "Member C Org"}
    assert not {OWNER, MEMBER_B, MEMBER_C} & set(response.text.replace('"', " ").split())
    assert all(MEMBER_B not in r["membership_id"].replace(rid("mem-opaque-b"), "") for r in rows)


async def test_an_organisation_that_is_not_in_the_network_is_told_nothing(two: _World) -> None:
    two.app.state.network_admin = two.services
    outsider = "org-outsider"
    app = _app((OWNER, MEMBER_B, MEMBER_C, outsider), two.services, two.clock)
    async with _client(app) as client:
        headers = _bearer(TA, outsider)
        leave = await client.post(f"/network-admin/network/{NETWORK_ID}/leave", headers=headers)
        mine = await client.get(
            f"/network-admin/network/{NETWORK_ID}/listings/mine", headers=headers
        )
        propose = await client.post(
            "/network-admin/grants",
            json={"network_id": NETWORK_ID, "scope": "capacity"},
            headers=headers,
        )
        networks = await client.get("/network-admin/networks", headers=headers)
    assert (leave.status_code, mine.status_code, propose.status_code) == (404, 404, 404)
    assert networks.json() == {"networks": []}


async def test_a_tenant_named_in_a_query_a_header_or_a_cookie_is_ignored(two: _World) -> None:
    two.seed_grants()
    async with _client(two.app) as client:
        response = await client.get(
            f"/network-admin/grants?tenant={MEMBER_C}&tenant_id={MEMBER_C}",
            headers={**_bearer(TA, MEMBER_B), "X-Tenant": MEMBER_C, "Cookie": f"tenant={MEMBER_C}"},
        )
    assert {g["organisation_name"] for g in response.json()["grants"]} == {"Member B Org"}


async def test_a_whole_administration_over_http_and_no_body_names_a_tenant_an_account_or_a_person(
    two: _World,
) -> None:
    seen: list[str] = []
    owner = _bearer(NA, OWNER, "o")
    outsider = "org-new"
    two.directory.tenants[outsider] = active_tenant(outsider, "New Org")
    app = _app((OWNER, MEMBER_B, MEMBER_C, outsider), two.services, two.clock)
    async with _client(app) as client:

        async def call(method: str, path: str, headers: dict[str, str], body: Any = None) -> Any:
            response = await client.request(method, path, json=body, headers=headers)
            seen.append(response.text)
            assert response.status_code < 400, (path, response.text)
            return response.json()

        net = f"/network-admin/network/{NETWORK_ID}"
        invited = await call("POST", f"{net}/members", owner, {"tenant_id": outsider})
        joiner = _bearer(TA, outsider, "j")
        await call(
            "POST",
            f"/network-admin/memberships/{invited['membership_id']}/accept",
            joiner,
            {"agreement_version": 1},
        )
        two.world.services[(outsider, SERVICE_ID)] = sample_profile()
        grant = await call(
            "POST",
            "/network-admin/grants",
            joiner,
            {"network_id": NETWORK_ID, "scope": "directory"},
        )
        assert (await call("POST", f"/network-admin/grants/{grant['id']}/approve", joiner))[
            "effective"
        ] is False
        assert (await call("POST", f"/network-admin/grants/{grant['id']}/approve", owner))[
            "effective"
        ] is True
        listing = await call("POST", f"{net}/listings", joiner, {"service_id": SERVICE_ID})
        await call("POST", f"{net}/listings/{listing['id']}/admit", owner)
        await call("GET", f"{net}/listings", owner)
        await call("GET", f"{net}/projection", owner)
        await call("POST", f"{net}/agreement", owner, {"reference": "DSA-2026-2", "version": 2})
        await call("GET", "/network-admin/networks", joiner)
        await call("POST", f"/network-admin/grants/{grant['id']}/end", joiner)
        grants = await call("GET", "/network-admin/grants", joiner)
        assert [g["status"] for g in grants["grants"]] == ["ended"]
        await call("POST", f"{net}/leave", joiner)
    text = " ".join(seen)
    assert "stf-" not in text and "acct-" not in text
    assert OWNER not in text and MEMBER_B not in text and MEMBER_C not in text
    # the joining organisation's id is not in any body either, only its name
    assert outsider not in text and "New Org" in text


# ---------------------------------------------------------------- 3. a whole flow on the real graph


@pytest_asyncio.fixture(loop_scope="session")
async def connection(harness_driver: AsyncDriver) -> AsyncIterator[Neo4jConnection]:
    conn = Neo4jConnection(
        os.environ["NEO4J_URI"], os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]
    )
    await conn.open()
    try:
        yield conn
    finally:
        await conn.close()


@pytest_asyncio.fixture(loop_scope="session")
async def rig(
    harness_driver: AsyncDriver,
    connection: Neo4jConnection,
    run_identity: RunIdentity,
    clean_graph: None,
) -> AsyncIterator[AdminRig]:
    built = await AdminRig.build(harness_driver, connection, world_ids(run_identity))
    await built.make_network()
    yield built
    await built.cleanup()


async def test_invite_accept_grant_list_and_leave_over_http_on_a_real_graph(rig: AdminRig) -> None:
    services = NetworkAdminServices(
        query=rig.admin_query,
        invite=rig.invite,
        accept=rig.accept,
        leave=rig.leave,
        remove=rig.remove,
        agreement=rig.record_agreement,
        grants=rig.grant_query,
        propose=rig.propose,
        approve=rig.approve,
        decline=rig.decline,
        end=rig.end_grant,
        revise=rig.revise,
        listings=rig.listing_query,
        request_listing=rig.request_listing,
        decide_listing=rig.decide_listing,
    )
    member = rig.ids.members[0]
    app = _app((rig.ids.owner, member), services, rig.clock)
    owner, mine = _bearer(NA, rig.ids.owner, "o"), _bearer(TA, member, "m")
    net = f"/network-admin/network/{rig.ids.network}"
    async with _client(app) as client:
        invited = (
            await client.post(f"{net}/members", json={"tenant_id": member}, headers=owner)
        ).json()
        assert (
            await client.post(
                f"/network-admin/memberships/{invited['membership_id']}/accept",
                json={"agreement_version": 1},
                headers=mine,
            )
        ).status_code == 200
        gid = (
            await client.post(
                "/network-admin/grants",
                json={"network_id": rig.ids.network, "scope": "capacity"},
                headers=mine,
            )
        ).json()["id"]
        first = await client.post(f"/network-admin/grants/{gid}/approve", headers=mine)
        second = await client.post(f"/network-admin/grants/{gid}/approve", headers=owner)
        assert (first.json(), second.json()) == ({"effective": False}, {"effective": True})
        grants = (await client.get("/network-admin/grants", headers=mine)).json()["grants"]
        assert [(g["scope"], g["status"], g["effective"]) for g in grants] == [
            ("capacity", "approved", True)
        ]
        # another organisation of the same network cannot touch it
        stranger = _bearer(TA, rig.ids.owner, "t")
        assert (
            await client.post(f"/network-admin/grants/{gid}/end", headers=stranger)
        ).status_code == 404
        assert (
            await client.post(f"/network-admin/grants/{gid}/end", headers=mine)
        ).status_code == 200
        left = await client.post(f"{net}/leave", headers=mine)
        assert left.status_code == 200 and left.json()["status"] == "left"
        members = (await client.get(f"{net}/members", headers=owner)).json()["members"]
        assert sorted(m["status"] for m in members) == ["active", "left"]
    assert await rig.audit_use_cases(rig.ids.network) == [
        "CreateNetwork",
        "InviteMember",
        "AcceptMembership",
        "ProposeGrant",
        "ApproveGrant",
        "ApproveGrant",
        "EndGrant",
        "LeaveNetwork",
    ]
    assert GrantScope.CAPACITY.value == "capacity"
    _ = (make_listing, make_owner_membership)
