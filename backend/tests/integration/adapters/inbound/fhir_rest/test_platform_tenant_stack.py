"""The platform's and the tenant administrator's routes on a real Neo4j, end to end (TEN-075,
TEN-084, TEN-043, TEN-073): real use cases, the real graph, the real cross-tenant guard, the real
platform chain and the real REST edge.

The platform records and the registry carry no tenant, so the module runs on a private container
(`schema`), emptied for each test, with two active tenants and, in one test, a third that is being
provisioned. What is proved that the unit tests (stand-ins) cannot:

- the operator provisions a tenant over HTTP and the registry, the tenant's own chain and the
  platform chain all say so, in fixed words and with no number or secret in the platform chain;
- a suspension, a resume and an offboarding reach the REST edge of the same process at once (the
  edge's cache is forgotten), and only for the tenant they name;
- the support-ticket flow works through the real guard: the request is in both chains, the
  administrator's approval issues a code that opens one access for one tenant, the tenant's own
  chain and the platform chain verify and hold every step, the administrator's access log (read from
  the tenant's chain) shows the platform's people, and another tenant sees none of it;
- no standing access: a code opens once, a revocation ends the access, an elapsed time ends it;
- a tenant administrator configures their own tenant (versions with a diff, two approvers for a
  clinical change, contacts, an email channel, retention, the directory, role mappings) and none of
  it is visible to another tenant, and the text channel is refused.

Written in build wave 9 (bundle W9C) and run there. Synthetic values only.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from neo4j import AsyncDriver

from diucs.adapters.inbound.fhir_rest.app import create_app
from diucs.adapters.inbound.fhir_rest.auth import BFF_SECRET_NAME
from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.tokens import TEST_BFF_SECRET, issue_test_token
from diucs.application.cross_tenant_guard import CrossTenantDenied, PlatformPrincipal
from diucs.application.platform_services import PlatformServices
from diucs.application.use_cases.cross_tenant_tickets import UseTicketCommand
from diucs.bootstrap.container import Container, build_for_tests
from diucs.bootstrap.platform_services import install_platform_routes
from diucs.bootstrap.provisioning import AuditHeads
from diucs.domain.codes import Role
from diucs.domain.model.tenant import OrganisationType, Tenant, TenantStatus
from diucs.domain.rules.bff_token import OperatorClaims, encode_operator_token
from diucs.domain.rules.support import SUPPORT_ACCESS_VALID_FOR, SUPPORT_CODE_SECRET
from tests.support.neo4j import ThrowawayNeo4j, wipe_all
from tests.support.tenancy import as_tenant

pytestmark = [pytest.mark.asyncio(loop_scope="session"), pytest.mark.schema]

A, B, C = "stack-alpha", "stack-bravo", "stack-charlie"
NOW = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
KEY = b"synthetic-platform-key-for-the-stack-integration-01"
OPERATOR_REF = "ref-platform-operator-0123456"
SUPPORT_REF = "ref-support-person-0123456789"
OTHER_SUPPORT_REF = "ref-another-support-9876543210"
JSON = {"Content-Type": "application/json"}
REASON = "A reporter cannot sign in on the tenant host."
FAR = datetime(2030, 1, 1, tzinfo=UTC)


@dataclass
class Stack:
    app: FastAPI
    client: AsyncClient
    container: Container
    clock: FixedClock
    driver: AsyncDriver
    counter: list[int]

    def key(self) -> dict[str, str]:
        self.counter[0] += 1
        return {"Idempotency-Key": f"stack-key-{self.counter[0]:05d}"}

    async def send(self, method: str, path: str, headers: dict[str, str], body: Any = None) -> Any:
        sent = {**headers}
        if method != "GET":
            sent |= self.key()
        if method in ("POST", "PUT"):
            sent |= JSON
        return await self.client.request(method, path, json=body, headers=sent)


def operator(role: Role = Role.PLATFORM_OPERATOR, sub: str | None = None) -> dict[str, str]:
    reference = sub or (OPERATOR_REF if role is Role.PLATFORM_OPERATOR else SUPPORT_REF)
    token = encode_operator_token(
        OperatorClaims(sub=reference, role=role, expires_at=FAR), TEST_BFF_SECRET
    )
    return {"Authorization": f"Bearer {token}"}


def support(sub: str = SUPPORT_REF) -> dict[str, str]:
    return operator(Role.SUPPORT, sub)


def admin(tenant: str = A, sub: str = "admin-ref-0001", epoch: int = 1) -> dict[str, str]:
    token = issue_test_token(Role.TENANT_ADMIN, [], sub, tenant=tenant, epoch=epoch, expires_at=FAR)
    return {"Authorization": f"Bearer {token}"}


def staff(tenant: str, role: Role = Role.LEAD, epoch: int = 1) -> dict[str, str]:
    token = issue_test_token(role, [], "prac-1", tenant=tenant, epoch=epoch, expires_at=FAR)
    return {"Authorization": f"Bearer {token}"}


async def _make_active(container: Container, tenant_id: str) -> None:
    created = Tenant(
        id=tenant_id,
        display_name=f"Org {tenant_id}",
        legal_name=f"Org {tenant_id} Ltd",
        organisation_type=OrganisationType.OTHER,
        status=TenantStatus.PROVISIONING,
        created_at=NOW - timedelta(days=30),
    )
    await container.tenant_registry.create(created)
    with as_tenant(tenant_id):
        await AuditHeads(container.neo4j).ensure_audit_head()
    activated = replace(created, status=TenantStatus.ACTIVE, activated_at=NOW - timedelta(days=29))
    assert await container.tenant_registry.save(
        activated, expected_epoch=1, expected_status=TenantStatus.PROVISIONING
    )


@pytest_asyncio.fixture(loop_scope="session")
async def stack(own_neo4j: tuple[ThrowawayNeo4j, AsyncDriver]) -> AsyncIterator[Stack]:
    neo4j, driver = own_neo4j
    await wipe_all(driver)
    connection = Neo4jConnection(neo4j.uri, neo4j.user, neo4j.password)
    await connection.open()
    clock = FixedClock(NOW)
    container = build_for_tests(
        clock=clock, neo4j=connection, secrets=FixedSecretStore({SUPPORT_CODE_SECRET: KEY})
    )
    await _make_active(container, A)
    await _make_active(container, B)
    app = create_app(container)
    app.state.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})
    app.state.cache = container.cache
    install_platform_routes(app, container)
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        try:
            yield Stack(app, client, container, clock, driver, [0])
        finally:
            await connection.close()
            await wipe_all(driver)


async def _tenant_chain(stack: Stack, tenant: str) -> list[Any]:
    with as_tenant(tenant):
        async with stack.container.uow_factory() as uow:
            assert await uow.audit.verify_chain()
            return list(await uow.audit.records())


async def _platform_chain(stack: Stack) -> list[Any]:
    assert await stack.container.platform_audit.verify()
    return await stack.container.platform_audit.entries(0, 200)


def _services(stack: Stack) -> PlatformServices:
    services: PlatformServices = stack.app.state.platform_services
    return services


# ---------------------------------------------------------------- provisioning


async def test_the_operator_provisions_a_tenant_and_the_three_records_say_so(stack: Stack) -> None:
    a_before = await stack.container.tenants.get(A)
    b_chain = len(await _tenant_chain(stack, B))

    created = await stack.send(
        "PUT",
        f"/platform/tenants/{C}",
        operator(),
        {
            "displayName": "Charlie Organisation",
            "legalName": "Charlie Organisation Ltd",
            "organisationType": "icb",
        },
    )
    host = await stack.send(
        "PUT", f"/platform/tenants/{C}/host", operator(), {"host": "c.example.org"}
    )
    number = await stack.send(
        "POST",
        f"/platform/tenants/{C}/numbers",
        operator(),
        {"e164": "+447700900321", "accountSid": "AC" + "3" * 32, "senderLabel": "Charlie"},
    )
    references = await stack.send(
        "PUT", f"/platform/tenants/{C}/references", operator(), {"dsaRef": "DSA-7"}
    )
    detail = await stack.send("GET", f"/platform/tenants/{C}", operator())

    assert created.status_code == 201 and created.json()["recorded"] is True
    assert (host.status_code, number.status_code, references.status_code) == (200, 201, 200)
    body = detail.json()
    assert body["tenant"]["status"] == "provisioning" and body["host"] == "c.example.org"
    assert body["tenant"]["references"]["dsa"] == "DSA-7"
    assert [n["e164"] for n in body["numbers"]] == ["+447700900321"]
    assert body["numbers"][0]["hasSecret"] is True and "twilio/" not in detail.text
    assert body["activation"]["ready"] is False
    assert "Host set" not in body["activation"]["blockers"]
    waiting_for_a_test_text = "At least one sender number active with a test text delivered"
    assert waiting_for_a_test_text in body["activation"]["blockers"]
    tested = await stack.send(
        "POST", f"/platform/tenants/{C}/numbers/tested", operator(), {"e164": "+447700900321"}
    )
    after = (await stack.send("GET", f"/platform/tenants/{C}", operator())).json()
    assert tested.status_code == 200
    assert waiting_for_a_test_text not in after["activation"]["blockers"]
    assert after["numbers"][0]["testedAt"] == "2026-10-30T09:00:00Z"
    # The tenant's own chain holds each step, by the operator.
    own = await _tenant_chain(stack, C)
    assert [r.entry.use_case for r in own] == [
        "CreateTenant",
        "SetTenantHost",
        "RecordTenantNumber",
        "RecordTenantReferences",
        "MarkNumberTested",
    ]
    assert {r.entry.actor.role for r in own} == {Role.PLATFORM_OPERATOR}
    # The platform's chain holds each step too, naming the tenant and the operator, and no number.
    platform = [r for r in await _platform_chain(stack) if r.tenant_id == C]
    assert [r.action for r in platform] == [
        "tenant-created",
        "tenant-host-set",
        "tenant-number-recorded",
        "tenant-references-recorded",
        "tenant-number-tested",
    ]
    assert {r.principal_ref for r in platform} == {OPERATOR_REF}
    assert "+447700900321" not in repr(platform) and "AC" + "3" * 32 not in repr(platform)
    # Nothing of another tenant changed.
    assert await stack.container.tenants.get(A) == a_before
    assert len(await _tenant_chain(stack, B)) == b_chain


async def test_the_list_shows_every_tenant_and_a_support_person_only_enough_to_name_one(
    stack: Stack,
) -> None:
    full = (await stack.send("GET", "/platform/tenants", operator())).json()["tenants"]
    short = (await stack.send("GET", "/platform/tenants", support())).json()["tenants"]

    assert [t["id"] for t in full] == [A, B]
    assert all(set(t) == {"id", "displayName", "status"} for t in short)


# ---------------------------------------------------------------- the lifecycle reaches the edge


async def test_a_suspension_and_a_resume_reach_the_edge_of_this_process_at_once(
    stack: Stack,
) -> None:
    assert (await stack.send("GET", "/tenant/overview", admin(A))).status_code == 200
    assert (await stack.send("GET", "/tenant/overview", admin(B))).status_code == 200

    suspended = await stack.send(
        "POST",
        f"/platform/tenants/{A}/suspension",
        operator(),
        {"mode": "blocked", "reason": "security-incident"},
    )
    # The edge of this process forgot the tenant: no wait for the record's cache to age.
    during = await stack.send("GET", "/tenant/overview", admin(A, epoch=1))
    other = await stack.send("GET", "/tenant/overview", admin(B))
    resumed = await stack.send("DELETE", f"/platform/tenants/{A}/suspension", operator())
    old = await stack.send("GET", "/tenant/overview", admin(A, epoch=1))
    fresh = await stack.send("GET", "/tenant/overview", admin(A, epoch=3))

    assert suspended.json()["epoch"] == 2 and suspended.json()["recorded"] is True
    assert during.status_code == 401 and other.status_code == 200
    assert resumed.json()["epoch"] == 3 and resumed.json()["resumedAgain"] is False
    assert old.status_code == 401  # a token from before the suspension stays refused
    assert fresh.status_code == 200
    own = [r.entry.use_case for r in await _tenant_chain(stack, A)]
    assert own[-2:] == ["SuspendTenant", "ResumeTenant"]
    assert [r.action for r in await _platform_chain(stack) if r.tenant_id == A] == [
        "tenant-suspended",
        "tenant-resumed",
    ]


async def test_a_read_only_suspension_lets_the_administrator_read_and_nothing_else(
    stack: Stack,
) -> None:
    await stack.send(
        "POST",
        f"/platform/tenants/{A}/suspension",
        operator(),
        {"mode": "read-only", "reason": "contract"},
    )

    read = await stack.send("GET", "/tenant/overview", admin(A, epoch=2))
    write = await stack.send(
        "PUT",
        "/tenant/contacts",
        admin(A, epoch=2),
        {"kind": "coordination-phone", "label": "Coordination", "value": "01234 567890"},
    )
    lead = await stack.send("GET", "/tenant/overview", staff(A, Role.LEAD, epoch=2))

    assert (read.status_code, write.status_code, lead.status_code) == (200, 401, 401)


async def test_an_offboarding_closes_the_tenant_at_the_edge_and_touches_no_other(
    stack: Stack,
) -> None:
    wrong = await stack.send(
        "POST", f"/platform/tenants/{B}/offboarding", operator(), {"confirmTenantId": A}
    )
    done = await stack.send(
        "POST", f"/platform/tenants/{B}/offboarding", operator(), {"confirmTenantId": B}
    )
    again = await stack.send(
        "POST", f"/platform/tenants/{B}/offboarding", operator(), {"confirmTenantId": B}
    )

    assert wrong.status_code == 400
    assert done.status_code == 200 and done.json()["noticeEndsAt"] == "2026-11-29T09:00:00Z"
    assert again.status_code == 409
    tenant = await stack.container.tenants.get(B)
    assert tenant is not None and tenant.status is TenantStatus.OFFBOARDING
    assert (await stack.send("GET", "/tenant/overview", admin(B))).status_code == 401
    assert (await stack.send("GET", "/tenant/overview", admin(A))).status_code == 200
    assert (await _tenant_chain(stack, B))[-1].entry.use_case == "StartTenantOffboarding"
    assert [r.action for r in await _platform_chain(stack) if r.tenant_id == B] == [
        "tenant-offboarding-started"
    ]


async def test_the_platform_chain_takes_appends_made_at_once_and_still_verifies(
    stack: Stack,
) -> None:
    import asyncio

    recorder = _services(stack).recorder
    await asyncio.gather(*(recorder.record(f"step-{n}", OPERATOR_REF, A) for n in range(10)))

    page = (await stack.send("GET", "/platform/audit?limit=5", operator())).json()
    verification = (await stack.send("GET", "/platform/audit/verification", operator())).json()

    assert [e["seq"] for e in page["entries"]] == [1, 2, 3, 4, 5] and page["next"] == 5
    assert verification == {"intact": True}


# ---------------------------------------------------------------- the support-ticket flow


async def _asked(stack: Stack, tenant: str = A, who: dict[str, str] | None = None) -> str:
    response = await stack.send(
        "POST",
        f"/platform/tenants/{tenant}/support-tickets",
        who or support(),
        {"reasonCode": "service-fault", "reason": REASON, "reference": "HD-1042"},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def test_the_whole_flow_goes_through_the_real_guard_and_both_chains_hold_every_step(
    stack: Stack,
) -> None:
    ticket_id = await _asked(stack)
    pending_b = (await stack.send("GET", "/tenant/support-tickets", admin(B))).json()
    pending_a = (await stack.send("GET", "/tenant/support-tickets", admin(A))).json()
    foreign = await stack.send("GET", f"/tenant/support-tickets/{ticket_id}", admin(B))

    approved = await stack.send("POST", f"/tenant/support-tickets/{ticket_id}/approval", admin(A))
    code = approved.json()["code"]
    opened = await stack.send(
        "POST", f"/platform/support-tickets/{ticket_id}/access", support(), {"code": code}
    )
    reused = await stack.send(
        "POST", f"/platform/support-tickets/{ticket_id}/access", support(), {"code": code}
    )

    assert pending_b["tickets"] == [] and [t["id"] for t in pending_a["tickets"]] == [ticket_id]
    assert foreign.status_code == 404
    assert approved.status_code == 200 and approved.json()["ticket"]["state"] == "approved"
    assert opened.status_code == 200 and opened.json()["ticket"]["state"] == "opened"
    assert opened.json()["access"]["tenantId"] == A
    assert reused.status_code == 404  # a code opens once
    # The tenant's own chain (real, verified) holds what the support person did, as the support
    # person, and the administrator's decision as the administrator.
    own = await _tenant_chain(stack, A)
    steps = [(r.entry.use_case, r.entry.action, r.entry.actor.role) for r in own]
    assert steps == [
        ("SupportAccessTicket", "support-ticket-requested", Role.SUPPORT),
        ("IssueSupportAccessCode", "support-access-code-issued", Role.TENANT_ADMIN),
        ("SupportAccessTicket", "support-ticket-approved", Role.TENANT_ADMIN),
        ("OpenCrossTenantAccess", "support-access-opened", Role.SUPPORT),
        ("SupportAccessTicket", "support-ticket-opened", Role.SUPPORT),
    ]
    assert code not in repr(own) and code.replace("-", "") not in repr(own)
    assert REASON not in repr(own)
    # The platform's chain (real, verified) holds the same steps, naming both people.
    platform = [r for r in await _platform_chain(stack) if r.tenant_id == A]
    assert [r.action for r in platform] == [
        "support-ticket-requested",
        "support-ticket-approved",
        "support-access-opened",
        "support-ticket-opened",
    ]
    assert [r.principal_ref for r in platform] == [
        SUPPORT_REF,
        "admin-ref-0001",
        SUPPORT_REF,
        SUPPORT_REF,
    ]
    assert code not in repr(platform)
    # Another tenant's chains hold none of it.
    assert [r.entry.use_case for r in await _tenant_chain(stack, B)] == []


async def test_the_administrators_access_log_shows_the_platforms_people_and_no_other_tenants(
    stack: Stack,
) -> None:
    ticket_id = await _asked(stack)
    code = (
        await stack.send("POST", f"/tenant/support-tickets/{ticket_id}/approval", admin(A))
    ).json()["code"]
    await stack.send(
        "POST", f"/platform/support-tickets/{ticket_id}/access", support(), {"code": code}
    )
    await stack.send(
        "POST",
        f"/platform/tenants/{A}/suspension",
        operator(),
        {"mode": "read-only", "reason": "contract"},
    )

    log = (await stack.send("GET", "/tenant/access-log", admin(A, epoch=2))).json()["entries"]
    other = (await stack.send("GET", "/tenant/access-log", admin(B))).json()["entries"]

    assert [(e["useCase"], e["role"]) for e in log] == [
        ("SuspendTenant", "platform-operator"),
        ("SupportAccessTicket", "support"),
        ("OpenCrossTenantAccess", "support"),
        ("SupportAccessTicket", "support"),
    ]
    assert {e["actorRef"] for e in log} == {OPERATOR_REF, SUPPORT_REF}
    assert all("tenant" not in e["entityIds"] for e in log) and other == []
    assert [e["action"] for e in log][-1] == "support-ticket-requested"


async def test_a_refusal_ends_the_request_and_issues_no_code(stack: Stack) -> None:
    ticket_id = await _asked(stack)

    refused = await stack.send("POST", f"/tenant/support-tickets/{ticket_id}/refusal", admin(A))
    approve_after = await stack.send(
        "POST", f"/tenant/support-tickets/{ticket_id}/approval", admin(A)
    )
    open_after = await stack.send(
        "POST", f"/platform/support-tickets/{ticket_id}/access", support(), {"code": "AAAA-AAAA"}
    )

    assert refused.json()["state"] == "refused"
    assert (approve_after.status_code, open_after.status_code) == (409, 404)
    own = [r.entry.action for r in await _tenant_chain(stack, A)]
    assert "support-access-code-issued" not in own and own[-1] == "support-ticket-refused"


async def test_revoking_ends_the_access_at_once_and_a_revoked_code_opens_nothing(
    stack: Stack,
) -> None:
    open_id = await _asked(stack, A)
    code = (
        await stack.send("POST", f"/tenant/support-tickets/{open_id}/approval", admin(A))
    ).json()["code"]
    await stack.send(
        "POST", f"/platform/support-tickets/{open_id}/access", support(), {"code": code}
    )
    unused_id = await _asked(stack, A, support(OTHER_SUPPORT_REF))
    unused_code = (
        await stack.send("POST", f"/tenant/support-tickets/{unused_id}/approval", admin(A))
    ).json()["code"]

    ended = await stack.send("DELETE", f"/tenant/support-tickets/{open_id}/access", admin(A))
    withdrawn = await stack.send("DELETE", f"/tenant/support-tickets/{unused_id}/access", admin(A))
    late = await stack.send(
        "POST",
        f"/platform/support-tickets/{unused_id}/access",
        support(OTHER_SUPPORT_REF),
        {"code": unused_code},
    )

    assert ended.json()["state"] == "revoked" and withdrawn.json()["state"] == "revoked"
    assert late.status_code == 404
    with pytest.raises(CrossTenantDenied):
        await _services(stack).tickets.using.execute(
            UseTicketCommand(
                PlatformPrincipal(account_ref=SUPPORT_REF, role=Role.SUPPORT),
                open_id,
                "read-session",
            )
        )
    own = [r.entry.action for r in await _tenant_chain(stack, A)]
    assert own.count("support-access-revoked") == 1 and "support-access-code-withdrawn" in own


async def test_no_access_stands_once_its_time_has_passed(stack: Stack) -> None:
    ticket_id = await _asked(stack)
    code = (
        await stack.send("POST", f"/tenant/support-tickets/{ticket_id}/approval", admin(A))
    ).json()["code"]
    await stack.send(
        "POST", f"/platform/support-tickets/{ticket_id}/access", support(), {"code": code}
    )
    principal = PlatformPrincipal(account_ref=SUPPORT_REF, role=Role.SUPPORT)
    used = await _services(stack).tickets.using.execute(
        UseTicketCommand(principal, ticket_id, "read-session")
    )

    stack.clock.advance(SUPPORT_ACCESS_VALID_FOR + timedelta(seconds=1))

    with pytest.raises(CrossTenantDenied):
        await _services(stack).tickets.using.execute(
            UseTicketCommand(principal, ticket_id, "read-session")
        )
    listed = (await stack.send("GET", "/platform/support-tickets", support())).json()["tickets"]
    assert used.tenant_id == A and listed[0]["state"] == "expired"
    assert [r.action for r in await _platform_chain(stack)][-2:] == [
        "support-ticket-opened",
        "support-access-used",
    ]


async def test_one_support_person_never_sees_or_uses_the_others_ticket(stack: Stack) -> None:
    mine = await _asked(stack, A, support())
    theirs = await _asked(stack, B, support(OTHER_SUPPORT_REF))

    own = (await stack.send("GET", "/platform/support-tickets", support())).json()["tickets"]
    peeking = await stack.send("GET", f"/platform/support-tickets/{theirs}", support())
    cancelling = await stack.send(
        "POST", f"/platform/support-tickets/{theirs}/cancellation", support()
    )

    assert [t["id"] for t in own] == [mine]
    assert (peeking.status_code, cancelling.status_code) == (404, 404)
    assert (
        await stack.send("GET", f"/platform/support-tickets/{mine}", support())
    ).status_code == 200


# ---------------------------------------------------------------- the tenant administrator


WORDING = {
    "systemName": "Alpha capacity view",
    "referralSystemName": "Alpha referrals",
    "coordinationTeamName": "The Alpha coordination team",
}


async def test_an_administrator_configures_their_own_tenant_and_no_other_sees_it(
    stack: Stack,
) -> None:
    empty = (await stack.send("GET", "/tenant/overview", admin(A))).json()
    draft = await stack.send(
        "POST",
        "/tenant/config/drafts",
        admin(A),
        {"basedOn": 0, "changes": WORDING, "reasonCode": "first-setup"},
    )
    approved = await stack.send("POST", "/tenant/config/versions/1/approval", admin(A))
    contact = await stack.send(
        "PUT",
        "/tenant/contacts",
        admin(A),
        {"kind": "coordination-phone", "label": "Coordination", "value": "01234 567890"},
    )
    channel = await stack.send(
        "POST",
        "/tenant/channels",
        admin(A),
        {"kind": "email", "senderLabel": "Alpha", "fromAddress": "alerts@example.org"},
    )
    retention = await stack.send("PUT", "/tenant/retention", admin(A), {"useDefaults": True})
    directory = await stack.send(
        "PUT",
        "/tenant/directory",
        admin(A),
        {"directoryId": "0f5a7c1e-3b2d-4c6a-9e8f-1a2b3c4d5e6f"},
    )
    mapping = await stack.send(
        "PUT",
        "/tenant/role-mappings",
        admin(A),
        {"groupObjectId": "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d", "role": "lead"},
    )

    mine = (await stack.send("GET", "/tenant/overview", admin(A))).json()
    theirs = (await stack.send("GET", "/tenant/overview", admin(B))).json()
    versions_b = (await stack.send("GET", "/tenant/config/versions", admin(B))).json()
    foreign = await stack.send("GET", "/tenant/config/versions/1", admin(B))

    assert empty["config"] is None and empty["contacts"] == [] and empty["channels"] == []
    assert draft.status_code == 201 and draft.json()["approvalsRequired"] == 1
    assert approved.json() == {
        "version": 1,
        "status": "current",
        "approvals": 1,
        "approvalsRequired": 1,
    }
    assert [
        contact.status_code,
        channel.status_code,
        retention.status_code,
        directory.status_code,
        mapping.status_code,
    ] == [204, 201, 200, 204, 204]
    assert mine["config"]["values"] == WORDING and mine["config"]["status"] == "current"
    assert mine["tenant"]["timeZone"] == "Europe/London"
    assert [c["label"] for c in mine["contacts"]] == ["Coordination"]
    assert [c["kind"] for c in mine["channels"]] == ["email"] and mine["channels"][0][
        "hasSecret"
    ] is False
    assert len(mine["retention"]) == 8
    assert [b["status"] for b in mine["bindings"]] == ["pending"]
    assert [m["role"] for m in mine["mappings"]] == ["lead"]
    assert theirs["config"] is None and theirs["contacts"] == [] and theirs["mappings"] == []
    assert theirs["channels"] == [] and theirs["bindings"] == [] and theirs["retention"] == []
    assert versions_b["versions"] == [] and foreign.status_code == 404


async def test_a_clinical_change_needs_two_people_and_the_author_is_not_one_of_them(
    stack: Stack,
) -> None:
    await stack.send("POST", "/tenant/config/drafts", admin(A), {"basedOn": 0, "changes": WORDING})
    await stack.send("POST", "/tenant/config/versions/1/approval", admin(A))

    draft = await stack.send(
        "POST",
        "/tenant/config/drafts",
        admin(A, sub="admin-ref-0001"),
        {"basedOn": 1, "changes": {"replyWindowMinutes": 20}, "reasonCode": "review"},
    )
    first = await stack.send(
        "POST", "/tenant/config/versions/2/approval", admin(A, sub="admin-ref-0002")
    )
    author = await stack.send(
        "POST", "/tenant/config/versions/2/approval", admin(A, sub="admin-ref-0001")
    )
    second = await stack.send(
        "POST", "/tenant/config/versions/2/approval", admin(A, sub="admin-ref-0003")
    )
    versions = (await stack.send("GET", "/tenant/config/versions", admin(A))).json()["versions"]

    assert draft.json() == {
        "version": 2,
        "changedKeys": ["replyWindowMinutes"],
        "clinicalKeys": ["replyWindowMinutes"],
        "approvalsRequired": 2,
    }
    assert first.json()["status"] == "pending-approval" and first.json()["approvals"] == 1
    assert author.status_code == 404  # the author may not approve a clinical change
    assert second.json() == {
        "version": 2,
        "status": "current",
        "approvals": 2,
        "approvalsRequired": 2,
    }
    assert [(v["version"], v["status"]) for v in versions] == [(2, "current"), (1, "superseded")]
    assert versions[0]["changedKeys"] == ["replyWindowMinutes"] and versions[0]["replaces"] == 1
    assert versions[0]["values"]["replyWindowMinutes"] == 20


async def test_a_draft_against_an_old_version_a_bad_value_and_the_text_channel_are_refused(
    stack: Stack,
) -> None:
    await stack.send("POST", "/tenant/config/drafts", admin(A), {"basedOn": 0, "changes": WORDING})
    await stack.send("POST", "/tenant/config/versions/1/approval", admin(A))

    stale = await stack.send(
        "POST", "/tenant/config/drafts", admin(A), {"basedOn": 0, "changes": {"systemName": "X y"}}
    )
    outside = await stack.send(
        "POST",
        "/tenant/config/drafts",
        admin(A),
        {"basedOn": 1, "changes": {"replyWindowMinutes": 90}},
    )
    nothing = await stack.send(
        "POST", "/tenant/config/drafts", admin(A), {"basedOn": 1, "changes": WORDING}
    )
    sms = await stack.send(
        "POST", "/tenant/channels", admin(A), {"kind": "sms", "senderLabel": "Alpha"}
    )
    foreign_secret = await stack.send(
        "POST",
        "/tenant/channels",
        admin(A),
        {
            "kind": "email",
            "senderLabel": "Alpha",
            "fromAddress": "alerts@example.org",
            "secretRef": f"smtp/{B}/password",
        },
    )

    assert (stale.status_code, outside.status_code, nothing.status_code) == (409, 400, 400)
    assert sms.status_code == 400 and foreign_secret.status_code == 400
    overview = (await stack.send("GET", "/tenant/overview", admin(A))).json()
    assert overview["channels"] == []


async def test_the_administrators_changes_are_in_their_own_chain_only(stack: Stack) -> None:
    await stack.send("POST", "/tenant/config/drafts", admin(A), {"basedOn": 0, "changes": WORDING})
    await stack.send("POST", "/tenant/config/versions/1/approval", admin(A))
    await stack.send(
        "PUT",
        "/tenant/contacts",
        admin(A),
        {"kind": "coordination-phone", "label": "Coordination", "value": "01234 567890"},
    )

    own = [r.entry.use_case for r in await _tenant_chain(stack, A)]
    other = [r.entry.use_case for r in await _tenant_chain(stack, B)]

    assert own == ["DraftTenantConfig", "ApproveTenantConfig", "RecordTenantContact"]
    assert other == []
