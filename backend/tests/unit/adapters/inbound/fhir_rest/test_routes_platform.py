"""The platform's routes (TEN-075): the operator console's back end and the support person's side
of a ticket, on the operator door.

The door first: a tenant token of any of the 13 roles is a 401, an operator token of the wrong
role is the 404 of a route that is not there, a token for the operator door that names a role no
operator has is a 401, and every claim of an operator token is checked (audience, signature,
expiry, subject, role, and no claim of a tenant token). Then the shapes: what each route answers,
what it refuses before it asks, that no body names a tenant, that a lifecycle step reaches the
platform chain, and that nothing the answers hold is a secret. Real use cases over recording
stand-ins (`tests/support/platform_routes_rig.py`); the same flows on a real graph are
`tests/integration/adapters/inbound/fhir_rest/test_routes_platform.py`.
"""

import itertools
from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient

from diucs.adapters.inbound.fhir_rest.routes_platform import PERMISSIONS
from diucs.domain.codes import Role
from diucs.domain.model.tenant import TenantStatus
from diucs.domain.rules import bff_token
from diucs.domain.rules.support_ticket import TicketState
from tests.support.platform_routes_rig import (
    JSON,
    NOW,
    OPERATOR_REF,
    SIGNING,
    SUPPORT_REF,
    FailingAudit,
    Rigs,
    build,
    forged_operator_audience_token,
    operator_token,
    ops,
    routes,
    tenant_headers,
)
from tests.support.provisioning_fakes import DIRECTORY_ID, TENANT
from tests.support.ticket_rig import REASON

pytestmark = pytest.mark.asyncio(loop_scope="session")

OPERATOR = frozenset({Role.PLATFORM_OPERATOR})
SUPPORT = frozenset({Role.SUPPORT})
EITHER = OPERATOR | SUPPORT

CREATE_BODY = {
    "displayName": "Brand New Organisation",
    "legalName": "Brand New Organisation Ltd",
    "organisationType": "icb",
}
SUSPEND_BODY = {"mode": "blocked", "reason": "security-incident"}
TICKET_BODY = {"reasonCode": "service-fault", "reason": REASON, "reference": "HD-1042"}

# method, path, body, the operator roles that may use it
ROUTES: list[tuple[str, str, Any, frozenset[Role]]] = [
    ("GET", "/platform/session", None, EITHER),
    ("GET", "/platform/tenants", None, EITHER),
    ("PUT", "/platform/tenants/brand-new", CREATE_BODY, OPERATOR),
    ("GET", f"/platform/tenants/{TENANT}", None, OPERATOR),
    ("PUT", f"/platform/tenants/{TENANT}/host", {"host": "new.example.org"}, OPERATOR),
    (
        "POST",
        f"/platform/tenants/{TENANT}/numbers",
        {"e164": "+447700900123", "accountSid": "AC" + "1" * 32, "senderLabel": "Sample"},
        OPERATOR,
    ),
    ("POST", f"/platform/tenants/{TENANT}/numbers/tested", {"e164": "+447700900123"}, OPERATOR),
    ("PUT", f"/platform/tenants/{TENANT}/references", {"dsaRef": "DSA-1"}, OPERATOR),
    (
        "POST",
        f"/platform/tenants/{TENANT}/directory/verification",
        {"directoryId": DIRECTORY_ID},
        OPERATOR,
    ),
    ("POST", f"/platform/tenants/{TENANT}/admin-invitation", {"mobile": "07700 900123"}, OPERATOR),
    ("POST", f"/platform/tenants/{TENANT}/activation", None, OPERATOR),
    ("POST", "/platform/tenants/act-org/suspension", SUSPEND_BODY, OPERATOR),
    ("DELETE", "/platform/tenants/act-org/suspension", None, OPERATOR),
    ("POST", "/platform/tenants/act-org/offboarding", {"confirmTenantId": "act-org"}, OPERATOR),
    ("GET", "/platform/audit", None, OPERATOR),
    ("GET", "/platform/audit/verification", None, OPERATOR),
    ("POST", "/platform/tenants/act-org/support-tickets", TICKET_BODY, SUPPORT),
    ("GET", "/platform/support-tickets", None, SUPPORT),
    ("GET", "/platform/support-tickets/st-1", None, SUPPORT),
    ("POST", "/platform/support-tickets/st-1/cancellation", None, SUPPORT),
    ("POST", "/platform/support-tickets/st-1/access", {"code": "AAAA-AAAA"}, SUPPORT),
    ("DELETE", "/platform/support-tickets/st-1/access", None, SUPPORT),
]


_KEYS = itertools.count(1)


async def send(
    client: AsyncClient,
    method: str,
    path: str,
    body: Any,
    headers: dict[str, str],
    *,
    key: str | None = None,
) -> Any:
    # A POST or PUT with no JSON content type is refused by the body-type check (415) before
    # routing, so a write with no body still says it is JSON (`{}`).
    unique = {"Idempotency-Key": key or f"w9c-route-key-{next(_KEYS):04d}"}
    sent = {**headers, **(unique if method != "GET" else {})}
    if method in ("POST", "PUT"):
        sent = {**sent, **JSON}
    return await client.request(method, path, json=body, headers=sent)


# ---------------------------------------------------------------- the door


@pytest.mark.parametrize("role", list(Role), ids=lambda r: r.value)
async def test_a_tenant_token_of_any_role_is_a_401_on_every_platform_route(role: Role) -> None:
    async with routes() as (_, client):
        for method, path, body, _allowed in ROUTES:
            response = await send(client, method, path, body, tenant_headers(role))

            assert response.status_code == 401, (method, path, role)


@pytest.mark.parametrize("role", [r for r in Role if r not in EITHER], ids=lambda r: r.value)
async def test_a_token_for_the_operator_door_that_names_another_role_is_a_401(role: Role) -> None:
    token = forged_operator_audience_token(role)
    async with routes() as (_, client):
        for method, path, body, _allowed in ROUTES:
            response = await send(client, method, path, body, {"Authorization": f"Bearer {token}"})

            assert response.status_code == 401, (method, path, role)


class _Tripwire:
    """Services that fail the request when anything is asked of them: a route that is refused by its
    role is shown never to have reached them (404), and one that is permitted is shown to have
    (500)."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the route asked the services for {name}")


@pytest.mark.parametrize("role", sorted(EITHER, key=lambda r: r.value), ids=lambda r: r.value)
async def test_the_role_matrix_of_every_platform_route(role: Role) -> None:
    r = build()
    r.app.state.platform_services = _Tripwire()
    async with r.client() as client:
        for method, path, body, allowed in ROUTES:
            if (method, path) == ("GET", "/platform/session"):
                continue  # the session reads the token only and asks no service
            response = await send(client, method, path, body, ops(role))

            if role in allowed:
                assert response.status_code == 500, (method, path, role)
            else:
                assert response.status_code == 404, (method, path, role)


async def test_no_token_is_a_401_on_every_platform_route() -> None:
    async with routes() as (_, client):
        for method, path, body, _allowed in ROUTES:
            assert (await send(client, method, path, body, {})).status_code == 401, (method, path)


def _forged(**changes: Any) -> str:
    body: dict[str, Any] = {
        "sub": OPERATOR_REF,
        "role": "platform-operator",
        "aud": bff_token.OPERATOR_AUDIENCE,
        "exp": int((NOW + timedelta(hours=1)).timestamp()),
    }
    body = {k: v for k, v in {**body, **changes}.items() if v is not ...}
    return bff_token._sealed(body, SIGNING)


@pytest.mark.parametrize(
    "token",
    [
        "claim: audience of the tenant door",
        "claim: no audience",
        "claim: an audience that is a list",
        "claim: a tenant (a tenant claim belongs to the other door)",
        "claim: an epoch",
        "claim: services",
        "claim: no subject",
        "claim: an empty subject",
        "claim: a role that is not a role",
        "claim: no role",
        "claim: a tenant role",
        "claim: expired",
        "claim: no expiry",
        "claim: an expiry that is text",
        "signed with another secret",
        "algorithm none",
        "not a token",
    ],
)
async def test_every_claim_of_an_operator_token_is_checked(token: str) -> None:
    other = bff_token._sealed(
        {
            "sub": OPERATOR_REF,
            "role": "platform-operator",
            "aud": "diucs-ops",
            "exp": int((NOW + timedelta(hours=1)).timestamp()),
        },
        b"another-signing-secret-that-is-long-enough-xyz",
    )
    expired = int((NOW - timedelta(seconds=1)).timestamp())
    tokens = {
        "claim: audience of the tenant door": _forged(aud="diucs-api"),
        "claim: no audience": _forged(aud=...),
        "claim: an audience that is a list": _forged(aud=["diucs-ops"]),
        "claim: a tenant (a tenant claim belongs to the other door)": _forged(tenant="tenant-a"),
        "claim: an epoch": _forged(epoch=1),
        "claim: services": _forged(services=[]),
        "claim: no subject": _forged(sub=...),
        "claim: an empty subject": _forged(sub=""),
        "claim: a role that is not a role": _forged(role="superuser"),
        "claim: no role": _forged(role=...),
        "claim: a tenant role": _forged(role="tenant-admin"),
        "claim: expired": _forged(exp=expired),
        "claim: no expiry": _forged(exp=...),
        "claim: an expiry that is text": _forged(exp="soon"),
        "signed with another secret": other,
        "algorithm none": "eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.e30.",
        "not a token": "not-a-token",
    }
    async with routes() as (_, client):
        response = await client.get(
            "/platform/session", headers={"Authorization": f"Bearer {tokens[token]}"}
        )

    assert response.status_code == 401
    assert response.json()["issue"][0]["code"] == "login"


async def test_a_well_formed_token_is_accepted_and_the_refusals_are_all_one_body() -> None:
    async with routes() as (_, client):
        ok = await client.get("/platform/session", headers=ops())
        refused = [
            await client.get("/platform/session", headers={"Authorization": f"Bearer {bad}"})
            for bad in ("x", _forged(aud="diucs-api"), _forged(exp=1))
        ]

    assert ok.status_code == 200
    assert {r.content for r in refused} == {refused[0].content}
    assert {r.headers["www-authenticate"] for r in refused} == {"Bearer"}


async def test_an_operator_token_is_a_401_on_the_tenant_door_too() -> None:
    async with routes() as (_, client):
        for path in ("/tenant/overview", "/tenant/support-tickets", "/fhir/Task"):
            response = await client.get(path, headers=ops())
            assert response.status_code == 401, path


# ---------------------------------------------------------------- the session


async def test_the_session_says_who_is_signed_in_until_when_and_what_the_role_may_do() -> None:
    async with routes() as (_, client):
        operator = await client.get("/platform/session", headers=ops())
        support = await client.get("/platform/session", headers=ops(Role.SUPPORT))

    assert operator.json() == {
        "role": "platform-operator",
        "accountRef": OPERATOR_REF,
        "expiresAt": "2026-10-30T10:00:00Z",
        "permissions": list(PERMISSIONS[Role.PLATFORM_OPERATOR]),
    }
    assert support.json()["role"] == "support" and support.json()["accountRef"] == SUPPORT_REF
    assert "tenants:lifecycle" not in support.json()["permissions"]
    assert "support:request" in support.json()["permissions"]
    assert operator.headers["cache-control"] == "no-store"


async def test_the_session_holds_no_secret_and_no_tenant() -> None:
    async with routes() as (_, client):
        body = (await client.get("/platform/session", headers=ops())).text

    assert "tenant" not in body.replace("tenants:", "")
    assert operator_token() not in body


# ---------------------------------------------------------------- the list and the detail


async def test_the_operator_sees_every_tenant_and_a_support_person_only_enough_to_name_one() -> (
    None
):
    async with routes() as (_, client):
        full = (await client.get("/platform/tenants", headers=ops())).json()["tenants"]
        short = (await client.get("/platform/tenants", headers=ops(Role.SUPPORT))).json()["tenants"]

    assert [row["id"] for row in full] == ["act-org", "new-org"]
    assert set(full[0]) == {
        "id",
        "displayName",
        "status",
        "organisationType",
        "host",
        "activatedAt",
    }
    assert [row["status"] for row in full] == ["active", "provisioning"]
    assert set(short[0]) == {"id", "displayName", "status"}


async def test_the_detail_of_a_provisioning_tenant_says_what_activation_waits_for() -> None:
    async with routes() as (r, client):
        r.fake.hosts[TENANT] = "new.example.org"
        body = (await client.get(f"/platform/tenants/{TENANT}", headers=ops())).json()

    assert body["tenant"]["id"] == TENANT and body["tenant"]["status"] == "provisioning"
    assert body["host"] == "new.example.org" and body["numbers"] == []
    assert body["activation"]["ready"] is False
    assert body["activation"]["blockers"]


async def test_the_detail_of_an_active_tenant_has_no_activation_and_a_missing_one_is_a_404() -> (
    None
):
    async with routes() as (_, client):
        active = await client.get("/platform/tenants/act-org", headers=ops())
        missing = await client.get("/platform/tenants/no-such-org", headers=ops())

    assert active.json()["activation"] is None
    assert missing.status_code == 404


@pytest.mark.parametrize(
    "path_id", ["Not-A-Tenant", "net-alliance", "a", "x" * 40, "platform", "default"]
)
async def test_a_path_that_is_not_a_tenant_id_is_the_404_of_a_route_that_is_not_there(
    path_id: str,
) -> None:
    async with routes() as (r, client):
        response = await client.get(f"/platform/tenants/{path_id}", headers=ops())

    assert response.status_code == 404
    assert r.audit.entries == []


# ---------------------------------------------------------------- creating and provisioning


async def test_a_tenant_is_created_in_provisioning_and_the_step_reaches_the_platform_chain() -> (
    None
):
    async with routes() as (r, client):
        response = await send(client, "PUT", "/platform/tenants/brand-new", CREATE_BODY, ops())

    assert response.status_code == 201
    assert response.json() == {"tenantId": "brand-new", "created": True, "recorded": True}
    assert r.fake.tenants["brand-new"].status is TenantStatus.PROVISIONING
    (entry,) = r.audit.entries
    assert (entry.action, entry.principal_ref, entry.tenant_id) == (
        "tenant-created",
        OPERATOR_REF,
        "brand-new",
    )
    assert entry.snapshot == {"organisationType": "icb"}


async def test_a_creation_that_is_run_again_finishes_and_says_so() -> None:
    async with routes() as (r, client):
        first = await send(client, "PUT", "/platform/tenants/brand-new", CREATE_BODY, ops())
        again = await client.put(
            "/platform/tenants/brand-new",
            json=CREATE_BODY,
            headers={**ops(), **JSON, "Idempotency-Key": "w9c-route-key-0002"},
        )

    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json()["created"] is False


async def test_the_same_key_and_body_is_replayed_and_another_body_is_refused() -> None:
    async with routes() as (r, client):
        same = "w9c-same-key-0001"
        first = await send(
            client, "PUT", "/platform/tenants/brand-new", CREATE_BODY, ops(), key=same
        )
        replay = await send(
            client, "PUT", "/platform/tenants/brand-new", CREATE_BODY, ops(), key=same
        )
        other = await send(
            client,
            "PUT",
            "/platform/tenants/brand-new",
            {**CREATE_BODY, "displayName": "Another"},
            ops(),
            key=same,
        )

    assert replay.status_code == 201 and replay.headers["idempotent-replay"] == "true"
    assert replay.content == first.content
    assert other.status_code == 422
    assert len(r.audit.entries) == 1


async def test_a_write_with_no_key_is_a_400_that_names_the_header_and_writes_nothing() -> None:
    async with routes() as (r, client):
        response = await client.put(
            "/platform/tenants/brand-new", json=CREATE_BODY, headers={**ops(), **JSON}
        )

    assert response.status_code == 400
    assert "Idempotency-Key" in response.text
    assert "brand-new" not in r.fake.tenants and r.audit.entries == []


@pytest.mark.parametrize(
    "extra",
    [{"tenant": "other-org"}, {"tenantId": "other-org"}, {"tenant_id": "x"}, {"role": "lead"}],
)
async def test_no_body_may_name_a_tenant_or_anything_else_it_is_not_for(
    extra: dict[str, Any],
) -> None:
    async with routes() as (r, client):
        response = await send(
            client, "PUT", "/platform/tenants/brand-new", {**CREATE_BODY, **extra}, ops()
        )

    assert response.status_code == 400
    assert "brand-new" not in r.fake.tenants


@pytest.mark.parametrize(
    "body",
    [
        {**CREATE_BODY, "organisationType": "bank"},
        {**CREATE_BODY, "displayName": ""},
        {**CREATE_BODY, "countryCode": "GBR"},
        {"displayName": "x"},
    ],
)
async def test_a_bad_creation_body_is_a_400_and_nothing_is_written(body: dict[str, Any]) -> None:
    async with routes() as (r, client):
        response = await send(client, "PUT", "/platform/tenants/brand-new", body, ops())

    assert response.status_code == 400
    assert "brand-new" not in r.fake.tenants and r.audit.entries == []


async def test_the_other_provisioning_steps_answer_in_fixed_words_and_record_no_value() -> None:
    async with routes() as (r, client):
        host = await send(
            client, "PUT", f"/platform/tenants/{TENANT}/host", {"host": "new.example.org"}, ops()
        )
        number = await send(
            client,
            "POST",
            f"/platform/tenants/{TENANT}/numbers",
            {"e164": "+447700900123", "accountSid": "AC" + "1" * 32, "senderLabel": "Sample"},
            ops(),
        )
        tested = await send(
            client,
            "POST",
            f"/platform/tenants/{TENANT}/numbers/tested",
            {"e164": "+447700900123"},
            ops(),
        )
        references = await send(
            client,
            "PUT",
            f"/platform/tenants/{TENANT}/references",
            {"dsaRef": "DSA-1", "dpiaRef": "DPIA-1"},
            ops(),
        )
        invited = await send(
            client,
            "POST",
            f"/platform/tenants/{TENANT}/admin-invitation",
            {"mobile": "07700 900123"},
            ops(),
        )

    assert host.status_code == 200 and host.json() == {"recorded": True}
    assert number.status_code == 201 and number.json()["channelId"] == "sms-447700900123"
    assert tested.status_code == 200
    assert references.json() == {"references": ["dpia_ref", "dsa_ref"], "recorded": True}
    assert invited.status_code == 201 and invited.json()["expiresAt"] == "2026-11-01T09:00:00Z"
    assert r.stubs.invite.commands[0].mobile == "07700 900123"
    assert [e.action for e in r.audit.entries] == [
        "tenant-host-set",
        "tenant-number-recorded",
        "tenant-number-tested",
        "tenant-references-recorded",
        "tenant-admin-invited",
    ]
    chain = repr(r.audit.entries) + repr(r.world.audit)
    for value in ("07700 900123", "+447700900123", "new.example.org", "AC" + "1" * 32):
        assert value not in repr(r.audit.entries), value
    assert "07700 900123" not in chain


async def test_a_value_another_tenant_holds_is_a_409_and_the_step_is_not_recorded() -> None:
    async with routes() as (r, client):
        await r.fake.set_host("act-org", "taken.example.org")
        response = await send(
            client, "PUT", f"/platform/tenants/{TENANT}/host", {"host": "taken.example.org"}, ops()
        )

    assert response.status_code == 409
    assert r.audit.entries == []


async def test_the_directory_the_tenant_bound_is_verified_by_the_operator() -> None:
    async with routes() as (r, client):
        from diucs.domain.model.tenant_records import BindingStatus, EntraBinding

        r.world.config.binding_list = [EntraBinding(DIRECTORY_ID, BindingStatus.PENDING)]
        response = await send(
            client,
            "POST",
            f"/platform/tenants/{TENANT}/directory/verification",
            {"directoryId": DIRECTORY_ID},
            ops(),
        )

    assert response.status_code == 200 and response.json() == {"recorded": True}
    assert r.fake.directories[TENANT] == DIRECTORY_ID
    assert r.audit.entries[-1].action == "tenant-directory-verified"


# ---------------------------------------------------------------- the lifecycle


async def test_a_tenant_that_is_not_ready_is_not_activated_and_the_409_names_what_is_missing() -> (
    None
):
    async with routes() as (r, client):
        response = await send(client, "POST", f"/platform/tenants/{TENANT}/activation", None, ops())

    assert response.status_code == 409
    assert "Activation is unavailable until:" in response.json()["issue"][0]["diagnostics"]
    assert r.fake.tenants[TENANT].status is TenantStatus.PROVISIONING
    assert r.audit.entries == []


async def test_suspending_a_tenant_tells_the_edge_and_the_platform_chain() -> None:
    async with routes() as (r, client):
        response = await send(
            client, "POST", "/platform/tenants/act-org/suspension", SUSPEND_BODY, ops()
        )

    assert response.status_code == 200
    assert response.json() == {
        "tenantId": "act-org",
        "epoch": 2,
        "mode": "blocked",
        "recorded": True,
    }
    assert r.told == ["act-org"]
    (entry,) = r.audit.entries
    assert entry.action == "tenant-suspended" and entry.tenant_id == "act-org"
    assert entry.snapshot == {"mode": "blocked", "reason": "security-incident", "epoch": 2}


@pytest.mark.parametrize(
    "body",
    [
        {"mode": "blocked"},
        {"mode": "sleepy", "reason": "contract"},
        {"mode": "blocked", "reason": "because I said so"},
        {"mode": "blocked", "reason": "contract", "note": "x"},
    ],
)
async def test_a_suspension_takes_only_the_fixed_modes_and_reasons(body: dict[str, Any]) -> None:
    async with routes() as (r, client):
        response = await send(client, "POST", "/platform/tenants/act-org/suspension", body, ops())

    assert response.status_code == 400
    assert r.fake.tenants["act-org"].status is TenantStatus.ACTIVE and r.told == []


async def test_a_tenant_that_is_not_active_cannot_be_suspended() -> None:
    async with routes() as (r, client):
        response = await send(
            client, "POST", f"/platform/tenants/{TENANT}/suspension", SUSPEND_BODY, ops()
        )

    assert response.status_code == 409 and r.told == [] and r.audit.entries == []


async def test_a_resume_answers_what_it_did_and_is_recorded() -> None:
    async with routes() as (r, client):
        response = await send(client, "DELETE", "/platform/tenants/act-org/suspension", None, ops())

    assert response.json() == {
        "tenantId": "act-org",
        "epoch": 3,
        "servicesPrompted": 2,
        "servicesAnnounced": 2,
        "resumedAgain": False,
        "recorded": True,
    }
    assert r.audit.entries[0].action == "tenant-resumed"


async def test_an_offboarding_needs_the_tenants_own_id_and_starts_the_notice_period() -> None:
    async with routes() as (r, client):
        wrong = await send(
            client,
            "POST",
            "/platform/tenants/act-org/offboarding",
            {"confirmTenantId": "new-org"},
            ops(),
        )
        done = await client.post(
            "/platform/tenants/act-org/offboarding",
            json={"confirmTenantId": "act-org"},
            headers={**ops(), **JSON, "Idempotency-Key": "w9c-route-key-0009"},
        )

    assert wrong.status_code == 400
    assert r.fake.tenants["act-org"].status is TenantStatus.OFFBOARDING
    assert done.json() == {
        "tenantId": "act-org",
        "startedAt": "2026-10-30T09:00:00Z",
        "noticeEndsAt": "2026-11-29T09:00:00Z",
        "recorded": True,
    }
    assert r.told == ["act-org"]
    assert r.audit.entries[-1].action == "tenant-offboarding-started"


async def test_a_step_that_is_done_and_could_not_be_recorded_says_so_and_is_not_undone() -> None:
    async with routes() as (r, client):
        r.audit.fail = True
        response = await send(
            client, "POST", "/platform/tenants/act-org/suspension", SUSPEND_BODY, ops()
        )

    assert response.status_code == 200 and response.json()["recorded"] is False
    assert r.fake.tenants["act-org"].status is TenantStatus.SUSPENDED
    assert "platform-audit" not in response.text


async def test_one_operator_step_never_touches_another_tenant() -> None:
    async with routes() as (r, client):
        before = r.fake.tenants[TENANT]
        await send(client, "POST", "/platform/tenants/act-org/suspension", SUSPEND_BODY, ops())

    assert r.fake.tenants[TENANT] == before
    assert all(e.tenant_id == "act-org" for e in r.audit.entries)


# ---------------------------------------------------------------- the platform chain


async def test_the_platform_chain_is_read_a_page_at_a_time_and_verified() -> None:
    from datetime import UTC, datetime

    from diucs.application.ports.outbound.platform_audit import PlatformAuditRecord

    async with routes() as (r, client):
        r.reader.records = [
            PlatformAuditRecord(
                seq=n,
                action="tenant-created",
                principal_ref=OPERATOR_REF,
                tenant_id="x-org",
                access_id=None,
                snapshot=None,
                at=datetime(2026, 10, 30, 9, n, tzinfo=UTC),
                chain_hash="h" * 64,
                previous_hash="p" * 64,
            )
            for n in range(1, 6)
        ]
        first = (await client.get("/platform/audit?limit=2", headers=ops())).json()
        last = (await client.get("/platform/audit?afterSeq=4&limit=2", headers=ops())).json()
        verification = (await client.get("/platform/audit/verification", headers=ops())).json()
        r.reader.intact = False
        broken = (await client.get("/platform/audit/verification", headers=ops())).json()

    assert [e["seq"] for e in first["entries"]] == [1, 2] and first["next"] == 2
    assert [e["seq"] for e in last["entries"]] == [5] and last["next"] is None
    assert set(first["entries"][0]) == {
        "seq",
        "action",
        "principalRef",
        "tenantId",
        "accessId",
        "snapshot",
        "at",
    }
    assert verification == {"intact": True} and broken == {"intact": False}


@pytest.mark.parametrize("query", ["limit=0", "limit=201", "afterSeq=-1", "limit=x"])
async def test_a_page_that_is_not_a_page_is_a_400(query: str) -> None:
    async with routes() as (r, client):
        response = await client.get(f"/platform/audit?{query}", headers=ops())

    assert response.status_code == 400 and r.reader.asked == []


# ---------------------------------------------------------------- the support person's tickets


async def _approve(r: Rigs, ticket_id: str, tenant: str = "act-org") -> str:
    return str((await r.tickets.approve(ticket_id, tenant)).code)


async def test_a_support_person_asks_one_tenant_and_reads_their_own_ticket() -> None:
    async with routes() as (r, client):
        asked = await send(
            client,
            "POST",
            "/platform/tenants/tenant-a/support-tickets",
            TICKET_BODY,
            ops(Role.SUPPORT),
        )
        ticket_id = asked.json()["id"]
        listed = (await client.get("/platform/support-tickets", headers=ops(Role.SUPPORT))).json()
        read = await client.get(f"/platform/support-tickets/{ticket_id}", headers=ops(Role.SUPPORT))

    assert asked.status_code == 201
    assert set(asked.json()) == {
        "id",
        "tenantId",
        "state",
        "reasonCode",
        "reason",
        "reference",
        "requestedAt",
        "validUntil",
        "decidedAt",
        "openedAt",
        "endedAt",
        "endedBy",
        "accessId",
    }
    assert asked.json()["state"] == "pending" and asked.json()["tenantId"] == "tenant-a"
    assert [t["id"] for t in listed["tickets"]] == [ticket_id]
    assert read.json() == asked.json()
    assert "decidedBy" not in asked.text and "grant" not in asked.text.lower()


async def test_a_ticket_for_a_tenant_that_is_not_open_is_the_404_of_a_route_that_is_not_there() -> (
    None
):
    async with routes() as (r, client):
        for tenant in ("no-such-org", "Not-A-Tenant"):
            response = await send(
                client,
                "POST",
                f"/platform/tenants/{tenant}/support-tickets",
                TICKET_BODY,
                ops(Role.SUPPORT),
            )
            assert response.status_code == 404, tenant

    assert r.tickets.tickets.rows == {}


@pytest.mark.parametrize(
    "body",
    [
        {**TICKET_BODY, "reason": "too short"},
        {**TICKET_BODY, "reason": "Ring the patient on 07700 900123 about this fault"},
        {**TICKET_BODY, "reasonCode": "because"},
        {**TICKET_BODY, "tenant": "tenant-b"},
        {"reasonCode": "other"},
    ],
)
async def test_a_bad_ticket_request_is_a_400_and_stores_nothing(body: dict[str, Any]) -> None:
    async with routes() as (r, client):
        response = await send(
            client, "POST", "/platform/tenants/tenant-a/support-tickets", body, ops(Role.SUPPORT)
        )

    assert response.status_code == 400
    assert r.tickets.tickets.rows == {}


async def test_a_second_live_ticket_for_the_same_tenant_is_a_409() -> None:
    async with routes() as (_, client):
        path = "/platform/tenants/tenant-a/support-tickets"
        first = await send(client, "POST", path, TICKET_BODY, ops(Role.SUPPORT))
        second = await send(client, "POST", path, TICKET_BODY, ops(Role.SUPPORT))

    assert (first.status_code, second.status_code) == (201, 409)


async def test_the_support_person_opens_with_the_code_and_ends_the_access() -> None:
    async with routes() as (r, client):
        asked = await send(
            client,
            "POST",
            "/platform/tenants/tenant-a/support-tickets",
            TICKET_BODY,
            ops(Role.SUPPORT),
        )
        ticket_id = asked.json()["id"]
        code = await _approve(r, ticket_id, "tenant-a")
        opened = await send(
            client,
            "POST",
            f"/platform/support-tickets/{ticket_id}/access",
            {"code": code},
            ops(Role.SUPPORT),
        )
        ended = await send(
            client,
            "DELETE",
            f"/platform/support-tickets/{ticket_id}/access",
            None,
            ops(Role.SUPPORT),
        )

    assert opened.status_code == 200
    assert opened.json()["ticket"]["state"] == "opened"
    assert opened.json()["access"]["tenantId"] == "tenant-a"
    assert opened.json()["access"]["expiresAt"] == "2026-10-30T10:00:00Z"
    assert code not in opened.text
    assert ended.json()["state"] == "ended" and ended.json()["endedBy"] == "support"
    assert r.tickets.platform.entries[-1].action == "support-ticket-ended"


async def test_a_wrong_code_and_another_persons_ticket_are_the_one_404() -> None:
    async with routes() as (r, client):
        asked = await send(
            client,
            "POST",
            "/platform/tenants/tenant-a/support-tickets",
            TICKET_BODY,
            ops(Role.SUPPORT),
        )
        ticket_id = asked.json()["id"]
        await _approve(r, ticket_id, "tenant-a")
        other = ops(Role.SUPPORT, sub="ref-another-support-9876543210")
        wrong = await send(
            client,
            "POST",
            f"/platform/support-tickets/{ticket_id}/access",
            {"code": "AAAA-AAAA"},
            ops(Role.SUPPORT),
        )
        theirs = await client.get(f"/platform/support-tickets/{ticket_id}", headers=other)
        cancel = await send(
            client, "POST", f"/platform/support-tickets/{ticket_id}/cancellation", None, other
        )

    assert (wrong.status_code, theirs.status_code, cancel.status_code) == (404, 404, 404)
    assert wrong.content == theirs.content
    assert r.tickets.tickets.rows[ticket_id].state is TicketState.APPROVED


async def test_the_support_person_cancels_a_request_nobody_has_decided() -> None:
    async with routes() as (_, client):
        asked = await send(
            client,
            "POST",
            "/platform/tenants/tenant-a/support-tickets",
            TICKET_BODY,
            ops(Role.SUPPORT),
        )
        cancelled = await send(
            client,
            "POST",
            f"/platform/support-tickets/{asked.json()['id']}/cancellation",
            None,
            ops(Role.SUPPORT),
        )

    assert cancelled.json()["state"] == "cancelled"


async def test_a_support_write_needs_a_key_and_a_ticket_id_must_look_like_one() -> None:
    async with routes() as (_, client):
        no_key = await client.post(
            "/platform/tenants/tenant-a/support-tickets",
            json=TICKET_BODY,
            headers={**ops(Role.SUPPORT), **JSON},
        )
        bad_id = await client.get("/platform/support-tickets/has space", headers=ops(Role.SUPPORT))

    assert no_key.status_code == 400 and "Idempotency-Key" in no_key.text
    assert bad_id.status_code in (400, 404)


async def test_the_support_persons_list_is_theirs_alone() -> None:
    async with routes() as (_, client):
        other = ops(Role.SUPPORT, sub="ref-another-support-9876543210")
        await send(
            client,
            "POST",
            "/platform/tenants/tenant-a/support-tickets",
            TICKET_BODY,
            ops(Role.SUPPORT),
        )
        await send(client, "POST", "/platform/tenants/tenant-b/support-tickets", TICKET_BODY, other)
        mine = (await client.get("/platform/support-tickets", headers=ops(Role.SUPPORT))).json()
        theirs = (await client.get("/platform/support-tickets", headers=other)).json()

    assert [t["tenantId"] for t in mine["tickets"]] == ["tenant-a"]
    assert [t["tenantId"] for t in theirs["tickets"]] == ["tenant-b"]


# ---------------------------------------------------------------- fail closed


async def test_a_process_with_no_platform_services_fails_closed_on_every_route() -> None:
    r = build(with_services=False)
    async with r.client() as client:
        for method, path, body, allowed in ROUTES:
            if method == "GET" and path == "/platform/session":
                continue  # the session reads the token only
            role = sorted(allowed, key=lambda x: x.value)[0]
            response = await send(client, method, path, body, ops(role))
            assert response.status_code == 500, (method, path)


async def test_a_write_with_no_cache_fails_closed() -> None:
    r = build()
    del r.app.state.cache
    async with r.client() as client:
        response = await send(client, "PUT", "/platform/tenants/brand-new", CREATE_BODY, ops())

    assert response.status_code == 500
    assert "brand-new" not in r.fake.tenants


async def test_no_answer_holds_a_token_a_secret_or_a_hash() -> None:
    async with routes() as (r, client):
        asked = await send(
            client,
            "POST",
            "/platform/tenants/tenant-a/support-tickets",
            TICKET_BODY,
            ops(Role.SUPPORT),
        )
        texts = [
            asked.text,
            (await client.get("/platform/tenants", headers=ops())).text,
            (await client.get(f"/platform/tenants/{TENANT}", headers=ops())).text,
        ]

    for text in texts:
        assert operator_token() not in text and "twilio/" not in text
        assert "auth-token" not in text and "grantHash" not in text


async def test_failing_audit_stand_in_is_the_one_the_rig_gives() -> None:
    assert isinstance(build().audit, FailingAudit)
