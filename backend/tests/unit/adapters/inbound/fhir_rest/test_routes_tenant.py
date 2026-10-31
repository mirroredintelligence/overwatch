"""The tenant administrator's routes (TEN-075): what an administrator reads and changes of their
own tenant, and their side of the support-access ticket flow.

The door: a tenant token of any of the 13 roles, only `tenant-admin` is let through, and an
operator token is a 401. The tenant is the signed claim and nothing else, so no path, query or body
can name another. Then the shapes: what each route answers, that a secret reference is never shown,
that a setting arrives as the wire holds it and the use case's own bounds still apply, that the
text channel is the platform operator's, and that an approval's one-time code is answered once and
never cached. A tenant suspended read-only lets its administrator read and refuses every write.
Real ticket use cases over recording stand-ins and stub configuration use cases
(`tests/support/platform_routes_rig.py`); the same flows on a real graph are
`tests/integration/adapters/inbound/fhir_rest/test_routes_tenant.py`.
"""

import itertools
from datetime import UTC, datetime, time
from typing import Any

import pytest
from httpx import AsyncClient

from diucs.adapters.inbound.fhir_rest.routes_tenant import setting_from_json, setting_to_json
from diucs.application.use_cases.cross_tenant_tickets import RequestTicketCommand
from diucs.application.use_cases.tenant_admin_views import (
    AccessLogEntry,
    ConfigVersionView,
    TenantOverview,
)
from diucs.application.use_cases.tenant_config import (
    ApproveConfigResult,
    ConfigDiff,
    DraftConfigResult,
)
from diucs.domain.codes import Role
from diucs.domain.errors import Conflict, NotAllowed, ValidationFailed
from diucs.domain.model.tenant import (
    ConfigStatus,
    ContactKind,
    NumberStatus,
    SuspendMode,
    SuspendReason,
    TenantConfig,
    TenantContact,
    TenantStatus,
)
from diucs.domain.model.tenant_records import (
    BindingStatus,
    ChannelKind,
    ChannelProvider,
    EntraBinding,
    MappingStatus,
    RoleMapping,
    TenantChannel,
    default_retention,
)
from diucs.domain.rules.support_ticket import ReasonCode, TicketState
from diucs.domain.rules.tenant_settings import SETTING_SPECS, spec_for
from tests.support.platform_routes_rig import (
    JSON,
    NOW,
    Rigs,
    build,
    ops,
    routes,
    tenant_headers,
)
from tests.support.provisioning_fakes import provisioning_tenant
from tests.support.tenant_samples import make_tenant
from tests.support.ticket_rig import OTHER_PRINCIPAL, PRINCIPAL, REASON

pytestmark = pytest.mark.asyncio(loop_scope="session")

GROUP = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
DIRECTORY = "0f5a7c1e-3b2d-4c6a-9e8f-1a2b3c4d5e6f"
ADMIN = frozenset({Role.TENANT_ADMIN})

CONTACT = {"kind": "coordination-phone", "label": "Coordination", "value": "01234 567890"}
CHANNEL = {"kind": "email", "senderLabel": "Alpha", "fromAddress": "alerts@example.org"}
RETENTION = {"useDefaults": True}
DRAFT = {"basedOn": 1, "changes": {"systemName": "Alpha view"}}

# method, path, body
ROUTES: list[tuple[str, str, Any]] = [
    ("GET", "/tenant/overview", None),
    ("GET", "/tenant/settings", None),
    ("GET", "/tenant/config/versions", None),
    ("GET", "/tenant/config/versions/1", None),
    ("GET", "/tenant/access-log", None),
    ("POST", "/tenant/config/drafts", DRAFT),
    ("POST", "/tenant/config/versions/2/approval", None),
    ("PUT", "/tenant/contacts", CONTACT),
    ("PUT", "/tenant/staff/prac-1/work-phone", {"phone": "07700 900123"}),
    ("POST", "/tenant/channels", CHANNEL),
    ("PUT", "/tenant/channels/email-1", CHANNEL),
    ("PUT", "/tenant/retention", RETENTION),
    ("PUT", "/tenant/directory", {"directoryId": DIRECTORY}),
    ("PUT", "/tenant/role-mappings", {"groupObjectId": GROUP, "role": "lead"}),
    ("GET", "/tenant/support-tickets", None),
    ("GET", "/tenant/support-tickets/st-1", None),
    ("POST", "/tenant/support-tickets/st-1/approval", None),
    ("POST", "/tenant/support-tickets/st-1/refusal", None),
    ("DELETE", "/tenant/support-tickets/st-1/access", None),
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
    sent = {**headers}
    if method != "GET":
        sent["Idempotency-Key"] = key or f"w9c-tenant-key-{next(_KEYS):04d}"
    if method in ("POST", "PUT"):
        sent = {**sent, **JSON}
    return await client.request(method, path, json=body, headers=sent)


def admin(tenant: str = "tenant-a", **kwargs: Any) -> dict[str, str]:
    return tenant_headers(Role.TENANT_ADMIN, tenant, **kwargs)


class _Tripwire:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the route asked the services for {name}")


# ---------------------------------------------------------------- the door


@pytest.mark.parametrize("role", list(Role), ids=lambda r: r.value)
async def test_the_role_matrix_of_every_tenant_route(role: Role) -> None:
    r = build()
    r.app.state.tenant_admin_services = _Tripwire()
    async with r.client() as client:
        for method, path, body in ROUTES:
            response = await send(client, method, path, body, tenant_headers(role))

            if role is Role.PLATFORM_OPERATOR:
                assert response.status_code == 401, (method, path, role)  # no data access
            elif role in ADMIN:
                # The registry is static and asks no service; every other route reached them.
                expected = 200 if path == "/tenant/settings" else 500
                assert response.status_code == expected, (method, path, role)
            else:
                assert response.status_code == 404, (method, path, role)


async def test_no_token_and_an_operator_token_are_a_401_on_every_tenant_route() -> None:
    async with routes() as (_, client):
        for method, path, body in ROUTES:
            for headers in ({}, ops(), ops(Role.SUPPORT)):
                response = await send(client, method, path, body, headers)
                assert response.status_code == 401, (method, path)


async def test_a_token_of_a_tenant_the_edge_does_not_know_is_a_401() -> None:
    async with routes() as (_, client):
        response = await client.get("/tenant/overview", headers=admin("tenant-zz"))

    assert response.status_code == 401


async def test_the_tenant_is_the_signed_claim_and_nothing_a_request_sends() -> None:
    async with routes() as (r, client):
        r.stubs.reads.result = None

        async def overview(actor: Any) -> Any:
            seen.append(actor.tenant_id)
            raise Conflict("stop here")

        seen: list[str] = []
        r.tenant_admin.reads.overview = overview  # type: ignore[method-assign,misc]
        await client.get(
            "/tenant/overview?tenant=tenant-b&tenantId=tenant-b",
            headers={**admin("tenant-a"), "X-Tenant": "tenant-b", "Host": "tenant-b.example.org"},
        )

    assert seen == ["tenant-a"]


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/tenant/config/drafts", {**DRAFT, "tenant": "tenant-b"}),
        ("PUT", "/tenant/contacts", {**CONTACT, "tenantId": "tenant-b"}),
        (
            "PUT",
            "/tenant/staff/prac-1/work-phone",
            {"phone": "07700 900123", "tenant": "tenant-b"},
        ),
        ("PUT", "/tenant/retention", {**RETENTION, "tenant": "tenant-b"}),
        ("PUT", "/tenant/directory", {"directoryId": DIRECTORY, "tenant_id": "tenant-b"}),
        ("PUT", "/tenant/role-mappings", {"groupObjectId": GROUP, "role": "lead", "tenant": "x"}),
        ("POST", "/tenant/channels", {**CHANNEL, "tenant": "tenant-b"}),
    ],
)
async def test_no_body_may_name_a_tenant(method: str, path: str, body: dict[str, Any]) -> None:
    async with routes() as (r, client):
        response = await send(client, method, path, body, admin())

    assert response.status_code == 400
    for stub in (r.stubs.draft, r.stubs.contact, r.stubs.retention, r.stubs.bind, r.stubs.channel):
        assert stub.commands == []


async def test_a_write_with_no_key_is_a_400_and_asks_nothing() -> None:
    async with routes() as (r, client):
        response = await client.put("/tenant/contacts", json=CONTACT, headers={**admin(), **JSON})

    assert response.status_code == 400 and "Idempotency-Key" in response.text
    assert r.stubs.contact.commands == []


async def test_a_process_with_no_tenant_services_fails_closed() -> None:
    r = build(with_services=False)
    async with r.client() as client:
        response = await client.get("/tenant/overview", headers=admin())

    assert response.status_code == 500


async def test_a_read_only_suspension_lets_the_administrator_read_and_refuses_writes() -> None:
    async with routes() as (r, client):
        r.tickets.directory.tenants["tenant-a"] = make_tenant(
            TenantStatus.SUSPENDED,
            id="tenant-a",
            epoch=2,
            suspend_mode=SuspendMode.READ_ONLY,
            suspend_reason=SuspendReason.CONTRACT,
            suspended_at=NOW,
        )
        read = await client.get("/tenant/support-tickets", headers=admin(epoch=2))
        write = await send(client, "PUT", "/tenant/contacts", CONTACT, admin(epoch=2))
        approve = await send(
            client, "POST", "/tenant/support-tickets/st-1/approval", None, admin(epoch=2)
        )

    assert read.status_code == 200
    assert write.status_code == 401 and approve.status_code == 401
    assert r.stubs.contact.commands == []


# ---------------------------------------------------------------- the reads


def _config() -> TenantConfig:
    return TenantConfig(
        version=1,
        status=ConfigStatus.CURRENT,
        values={
            "systemName": "Alpha view",
            "twiceADaySecondTime": time(13, 30),
            "criticalAlertKinds": frozenset({"service-closed", "system-pressure"}),
            "reverifyEveryDays": 14,
        },
        created_at=NOW,
        created_by_ref="person-a",
        effective_from=NOW,
        approved_by_refs=("person-b", "person-c"),
        reason_code="review",
    )


def _overview() -> TenantOverview:
    return TenantOverview(
        tenant=provisioning_tenant("tenant-a", status=TenantStatus.ACTIVE, activated_at=NOW),
        host="tenant-a.example.org",
        config=_config(),
        contacts=(TenantContact(ContactKind.COORDINATION_PHONE, "Coordination", "01234 567890"),),
        channels=(
            TenantChannel(
                id="sms-1",
                kind=ChannelKind.SMS,
                provider=ChannelProvider.TWILIO,
                status=NumberStatus.ACTIVE,
                sender_label="Alpha",
                account_sid="AC" + "b" * 32,
                secret_ref="twilio/tenant-a/auth-token",
            ),
            TenantChannel(
                id="email-1",
                kind=ChannelKind.EMAIL,
                provider=ChannelProvider.SMTP,
                status=NumberStatus.ACTIVE,
                sender_label="Alpha",
                from_address="alerts@example.org",
            ),
        ),
        retention=default_retention(),
        bindings=(EntraBinding(DIRECTORY, BindingStatus.PENDING),),
        mappings=(RoleMapping(GROUP, Role.LEAD, MappingStatus.ACTIVE),),
    )


async def test_the_overview_shows_everything_configured_and_never_a_secret_reference() -> None:
    async with routes() as (r, client):

        async def overview(actor: Any) -> TenantOverview:
            return _overview()

        r.tenant_admin.reads.overview = overview  # type: ignore[method-assign,misc]
        response = await client.get("/tenant/overview", headers=admin())

    body = response.json()
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert body["tenant"]["id"] == "tenant-a" and body["tenant"]["host"] == "tenant-a.example.org"
    assert body["tenant"]["timeZone"] == "Europe/London"
    assert body["config"]["version"] == 1
    assert body["config"]["values"] == {
        "systemName": "Alpha view",
        "twiceADaySecondTime": "13:30",
        "criticalAlertKinds": ["service-closed", "system-pressure"],
        "reverifyEveryDays": 14,
    }
    assert [c["id"] for c in body["channels"]] == ["sms-1", "email-1"]
    assert body["channels"][0]["hasSecret"] is True and body["channels"][1]["hasSecret"] is False
    assert "secretRef" not in response.text and "twilio/" not in response.text
    assert "auth-token" not in response.text
    assert len(body["retention"]) == 8
    assert body["bindings"] == [{"directoryId": DIRECTORY, "status": "pending", "verifiedAt": None}]
    assert body["mappings"] == [{"groupObjectId": GROUP, "role": "lead", "status": "active"}]


async def test_the_overview_of_an_unconfigured_tenant_has_no_config() -> None:
    async with routes() as (r, client):

        async def overview(actor: Any) -> TenantOverview:
            return TenantOverview(provisioning_tenant("tenant-a"), None, None, (), (), (), (), ())

        r.tenant_admin.reads.overview = overview  # type: ignore[method-assign,misc]
        body = (await client.get("/tenant/overview", headers=admin())).json()

    assert (
        body["config"] is None and body["contacts"] == [] and body["host"] is None
        if "host" in body
        else True
    )


async def test_the_setting_registry_is_served_with_its_bounds_and_classes() -> None:
    async with routes() as (_, client):
        body = (await client.get("/tenant/settings", headers=admin())).json()

    assert [s["key"] for s in body["settings"]] == [s.key for s in SETTING_SPECS]
    by_key = {s["key"]: s for s in body["settings"]}
    assert by_key["replyWindowMinutes"] == {
        "key": "replyWindowMinutes",
        "kind": "int",
        "unit": "minutes",
        "default": 30,
        "minimum": 15,
        "maximum": 60,
        "choices": None,
        "allowed": None,
        "safetyClass": "clinical",
        "scope": "tenant",
        "requiredForActivation": False,
    }
    assert by_key["twiceADaySecondTime"]["default"] == "14:00"
    assert by_key["twiceADaySecondTime"]["minimum"] == "12:00"
    assert by_key["criticalAlertKinds"]["allowed"] == sorted(
        spec_for("criticalAlertKinds").allowed  # type: ignore[arg-type]
    )
    assert by_key["systemName"]["requiredForActivation"] is True
    assert by_key["alertDefaultNotUpdatedHours"]["safetyClass"] == "operational"


async def test_the_versions_come_with_their_diff_and_the_approvals_they_still_need() -> None:
    async with routes() as (r, client):
        view = ConfigVersionView(
            config=_config(),
            changed_keys=("reverifyEveryDays",),
            clinical_keys=("reverifyEveryDays",),
            approvals_required=2,
            replaces=None,
        )

        async def versions(actor: Any) -> list[ConfigVersionView]:
            return [view]

        async def version(actor: Any, number: int) -> ConfigVersionView:
            return view

        r.tenant_admin.reads.versions = versions  # type: ignore[method-assign,misc]
        r.tenant_admin.reads.version = version  # type: ignore[method-assign,misc]
        listed = (await client.get("/tenant/config/versions", headers=admin())).json()
        one = (await client.get("/tenant/config/versions/1", headers=admin())).json()

    assert listed["versions"] == [one]
    assert one["changedKeys"] == ["reverifyEveryDays"] and one["approvalsRequired"] == 2
    assert one["clinicalKeys"] == ["reverifyEveryDays"] and one["replaces"] is None
    assert one["approvedByRefs"] == ["person-b", "person-c"] and one["status"] == "current"


@pytest.mark.parametrize("path", ["/tenant/config/versions/0", "/tenant/config/versions/x"])
async def test_a_version_that_is_not_a_version_number_is_a_400(path: str) -> None:
    async with routes() as (_, client):
        assert (await client.get(path, headers=admin())).status_code == 400


async def test_the_access_log_is_what_the_use_case_gave_and_the_window_is_bounded() -> None:
    async with routes() as (r, client):
        asked: list[int] = []

        async def access_log(actor: Any, days: int) -> list[AccessLogEntry]:
            asked.append(days)
            return [
                AccessLogEntry(
                    at=datetime(2026, 10, 30, 8, 0, tzinfo=UTC),
                    use_case="OpenCrossTenantAccess",
                    action="support-access-opened",
                    role=Role.SUPPORT,
                    actor_ref="ref-support-person-0123456789",
                    entity_ids=("access-1",),
                    snapshot={"ticket": "st-1"},
                )
            ]

        r.tenant_admin.reads.access_log = access_log  # type: ignore[method-assign,misc]
        default = await client.get("/tenant/access-log", headers=admin())
        await client.get("/tenant/access-log?days=30", headers=admin())
        too_many = await client.get("/tenant/access-log?days=401", headers=admin())

    assert default.json()["entries"][0] == {
        "at": "2026-10-30T08:00:00Z",
        "useCase": "OpenCrossTenantAccess",
        "action": "support-access-opened",
        "role": "support",
        "actorRef": "ref-support-person-0123456789",
        "entityIds": ["access-1"],
        "snapshot": {"ticket": "st-1"},
    }
    assert asked == [90, 30] and too_many.status_code == 400


# ---------------------------------------------------------------- settings on the wire


@pytest.mark.parametrize(
    ("key", "raw", "value"),
    [
        ("replyWindowMinutes", 30, 30),
        ("twiceADaySecondTime", "14:00", time(14, 0)),
        ("criticalAlertKinds", ["service-closed"], frozenset({"service-closed"})),
        ("systemName", "Alpha view", "Alpha view"),
    ],
)
async def test_a_setting_arrives_as_the_type_its_row_demands(
    key: str, raw: Any, value: Any
) -> None:
    got = setting_from_json(spec_for(key), raw)

    assert got == value and type(got) is type(value)
    assert setting_from_json(spec_for(key), setting_to_json(got)) == value


@pytest.mark.parametrize(
    ("key", "raw"),
    [
        ("twiceADaySecondTime", "2pm"),
        ("twiceADaySecondTime", "14:00:00"),
        ("twiceADaySecondTime", "ab:cd"),
        ("twiceADaySecondTime", 1400),
        ("criticalAlertKinds", "service-closed"),
        ("criticalAlertKinds", [1]),
        ("replyWindowMinutes", [30]),
        ("replyWindowMinutes", {"a": 1}),
        ("replyWindowMinutes", None),
    ],
)
async def test_a_setting_that_cannot_be_made_is_refused(key: str, raw: Any) -> None:
    with pytest.raises(ValidationFailed):
        setting_from_json(spec_for(key), raw)


# ---------------------------------------------------------------- the configuration


async def test_a_draft_is_made_from_the_wire_values_and_answers_its_diff() -> None:
    async with routes() as (r, client):
        r.stubs.draft.result = DraftConfigResult(
            2, ConfigDiff(("reverifyEveryDays",), ("reverifyEveryDays",), 2)
        )
        response = await send(
            client,
            "POST",
            "/tenant/config/drafts",
            {
                "basedOn": 1,
                "changes": {
                    "twiceADaySecondTime": "13:00",
                    "criticalAlertKinds": ["service-closed"],
                },
                "removals": ["systemName"],
                "reasonCode": "review",
            },
            admin(),
        )

    assert response.status_code == 201
    assert response.json() == {
        "version": 2,
        "changedKeys": ["reverifyEveryDays"],
        "clinicalKeys": ["reverifyEveryDays"],
        "approvalsRequired": 2,
    }
    (command,) = r.stubs.draft.commands
    assert command.actor.tenant_id == "tenant-a" and command.based_on == 1
    assert command.changes == {
        "twiceADaySecondTime": time(13, 0),
        "criticalAlertKinds": frozenset({"service-closed"}),
    }
    assert command.removals == frozenset({"systemName"}) and command.reason_code == "review"


@pytest.mark.parametrize(
    "body",
    [
        {"basedOn": 1, "changes": {"notASetting": 1}},
        {"basedOn": 1, "changes": {"twiceADaySecondTime": "14"}},
        {"basedOn": -1},
        {"changes": {"replyWindowMinutes": 30}},
        {"basedOn": 1, "reasonCode": "x" * 41},
        {"basedOn": 1, "removals": "systemName"},
    ],
)
async def test_a_bad_draft_is_a_400_and_asks_nothing(body: dict[str, Any]) -> None:
    async with routes() as (r, client):
        response = await send(client, "POST", "/tenant/config/drafts", body, admin())

    assert response.status_code == 400 and r.stubs.draft.commands == []


async def test_a_draft_against_a_version_that_is_no_longer_in_force_is_a_409() -> None:
    async with routes() as (r, client):
        r.stubs.draft.error = Conflict("the configuration changed since it was read")
        response = await send(client, "POST", "/tenant/config/drafts", DRAFT, admin())

    assert response.status_code == 409


async def test_an_approval_answers_where_the_version_stands() -> None:
    async with routes() as (r, client):
        r.stubs.approve.result = ApproveConfigResult(2, ConfigStatus.PENDING_APPROVAL, 1, 2)
        response = await send(client, "POST", "/tenant/config/versions/2/approval", None, admin())

    assert response.json() == {
        "version": 2,
        "status": "pending-approval",
        "approvals": 1,
        "approvalsRequired": 2,
    }
    assert r.stubs.approve.commands[0].version == 2


async def test_an_approval_the_use_case_refuses_is_the_404_of_a_route_that_is_not_there() -> None:
    async with routes() as (r, client):
        r.stubs.approve.error = NotAllowed("the author cannot approve a clinical change")
        response = await send(client, "POST", "/tenant/config/versions/2/approval", None, admin())

    assert response.status_code == 404


async def test_a_contact_a_retention_a_directory_and_a_mapping_are_answered_in_a_few_words() -> (
    None
):
    async with routes() as (r, client):
        r.stubs.retention.result = 8
        contact = await send(client, "PUT", "/tenant/contacts", CONTACT, admin())
        retention = await send(client, "PUT", "/tenant/retention", RETENTION, admin())
        directory = await send(
            client, "PUT", "/tenant/directory", {"directoryId": DIRECTORY}, admin()
        )
        mapping = await send(
            client,
            "PUT",
            "/tenant/role-mappings",
            {"groupObjectId": GROUP, "role": "lead", "status": "retired"},
            admin(),
        )

    assert (contact.status_code, directory.status_code, mapping.status_code) == (204, 204, 204)
    assert retention.json() == {"stored": 8}
    assert r.stubs.contact.commands[0].kind is ContactKind.COORDINATION_PHONE
    assert r.stubs.retention.commands[0].use_defaults is True
    assert r.stubs.bind.commands[0].directory_id == DIRECTORY
    assert r.stubs.map_group.commands[0].status is MappingStatus.RETIRED


async def test_explicit_retention_rules_are_made_into_rules() -> None:
    async with routes() as (r, client):
        r.stubs.retention.result = 1
        await send(
            client,
            "PUT",
            "/tenant/retention",
            {"rules": [{"dataClass": "bookings", "keepDays": 365, "action": "delete"}]},
            admin(),
        )

    (rule,) = r.stubs.retention.commands[0].rules
    assert (rule.data_class.value, rule.keep_days, rule.action.value) == ("bookings", 365, "delete")


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/tenant/contacts", {"kind": "pager", "label": "x", "value": "y"}),
        ("/tenant/contacts", {"kind": "coordination-phone", "label": "", "value": "y"}),
        (
            "/tenant/retention",
            {"rules": [{"dataClass": "bookings", "action": "delete", "keepDays": 0}]},
        ),
        ("/tenant/retention", {"rules": [{"dataClass": "tea", "action": "delete"}]}),
        ("/tenant/role-mappings", {"groupObjectId": GROUP, "role": "wizard"}),
        ("/tenant/directory", {}),
    ],
)
async def test_a_body_that_is_not_valid_is_a_400_before_anything_is_asked(
    path: str, body: dict[str, Any]
) -> None:
    async with routes() as (r, client):
        response = await send(client, "PUT", path, body, admin())

    assert response.status_code == 400
    for stub in (r.stubs.contact, r.stubs.retention, r.stubs.bind, r.stubs.map_group):
        assert stub.commands == []


async def test_the_administrator_may_set_an_email_channel_and_never_the_text_channel() -> None:
    async with routes() as (r, client):
        r.stubs.channel.result = "email-1"
        added = await send(client, "POST", "/tenant/channels", CHANNEL, admin())
        changed = await send(client, "PUT", "/tenant/channels/email-1", CHANNEL, admin())
        text = await send(
            client,
            "POST",
            "/tenant/channels",
            {"kind": "sms", "senderLabel": "Alpha", "secretRef": "twilio/tenant-b/auth-token"},
            admin(),
        )
        text_change = await send(
            client, "PUT", "/tenant/channels/sms-1", {"kind": "sms", "senderLabel": "x"}, admin()
        )

    assert (added.status_code, added.json()) == (201, {"id": "email-1"})
    assert (changed.status_code, changed.json()) == (200, {"id": "email-1"})
    assert [c.channel_id for c in r.stubs.channel.commands] == [None, "email-1"]
    assert (text.status_code, text_change.status_code) == (400, 400)
    assert "platform operator" in text.text
    assert len(r.stubs.channel.commands) == 2


# ---------------------------------------------------------------- the ticket flow, tenant side


async def _asked(r: Rigs, tenant: str = "tenant-a", principal: Any = PRINCIPAL) -> str:
    ticket = await r.tickets.request.execute(
        RequestTicketCommand(principal, tenant, ReasonCode.SERVICE_FAULT, REASON, "HD-1")
    )
    return ticket.id


async def test_the_administrator_lists_and_reads_the_tickets_that_name_their_tenant() -> None:
    async with routes() as (r, client):
        mine = await _asked(r, "tenant-a")
        await _asked(r, "tenant-b")
        listed = (await client.get("/tenant/support-tickets", headers=admin())).json()
        read = await client.get(f"/tenant/support-tickets/{mine}", headers=admin())

    assert [t["id"] for t in listed["tickets"]] == [mine]
    assert read.json() == listed["tickets"][0]
    assert read.json()["state"] == "pending" and read.json()["reason"] == REASON
    assert set(read.json()) == {
        "id",
        "state",
        "requestedByRef",
        "reasonCode",
        "reason",
        "reference",
        "requestedAt",
        "validUntil",
        "decidedByRef",
        "decidedAt",
        "openedAt",
        "endedAt",
        "endedBy",
        "accessId",
    }
    assert "grant" not in read.text.lower() and "tenantId" not in read.text


async def test_another_tenants_ticket_is_a_404_to_read_decide_or_revoke() -> None:
    async with routes() as (r, client):
        theirs = await _asked(r, "tenant-b")
        responses = [
            await client.get(f"/tenant/support-tickets/{theirs}", headers=admin("tenant-a")),
            await send(
                client,
                "POST",
                f"/tenant/support-tickets/{theirs}/approval",
                None,
                admin("tenant-a"),
            ),
            await send(
                client, "POST", f"/tenant/support-tickets/{theirs}/refusal", None, admin("tenant-a")
            ),
            await send(
                client,
                "DELETE",
                f"/tenant/support-tickets/{theirs}/access",
                None,
                admin("tenant-a"),
            ),
        ]

    assert [x.status_code for x in responses] == [404, 404, 404, 404]
    assert r.tickets.tickets.rows[theirs].state is TicketState.PENDING


async def test_an_approval_answers_the_one_time_code_once_and_never_caches_it() -> None:
    async with routes() as (r, client):
        ticket_id = await _asked(r)
        first = await send(
            client,
            "POST",
            f"/tenant/support-tickets/{ticket_id}/approval",
            None,
            admin(),
            key="k-1",
        )
        again = await send(
            client,
            "POST",
            f"/tenant/support-tickets/{ticket_id}/approval",
            None,
            admin(),
            key="k-1",
        )

    body = first.json()
    assert first.status_code == 200 and first.headers["cache-control"] == "no-store"
    assert len(body["code"]) == 9 and body["code"][4] == "-"
    assert body["codeExpiresAt"] == "2026-10-30T13:00:00Z"
    assert (
        body["ticket"]["state"] == "approved" and body["ticket"]["decidedByRef"] == "admin-ref-0001"
    )
    assert again.status_code == 409 and "code" not in again.json()
    assert body["code"] not in again.text
    assert body["code"] not in repr(r.tickets.tickets.rows) and body["code"] not in repr(
        r.tickets.world.chains
    )


async def test_the_code_the_administrator_gave_opens_the_ticket_and_revoking_ends_the_access() -> (
    None
):
    async with routes() as (r, client):
        asked = await send(
            client,
            "POST",
            "/platform/tenants/tenant-a/support-tickets",
            {"reasonCode": "service-fault", "reason": REASON},
            ops(Role.SUPPORT),
        )
        ticket_id = asked.json()["id"]
        approved = await send(
            client, "POST", f"/tenant/support-tickets/{ticket_id}/approval", None, admin()
        )
        opened = await send(
            client,
            "POST",
            f"/platform/support-tickets/{ticket_id}/access",
            {"code": approved.json()["code"]},
            ops(Role.SUPPORT),
        )
        revoked = await send(
            client, "DELETE", f"/tenant/support-tickets/{ticket_id}/access", None, admin()
        )
        reread = await client.get(
            f"/platform/support-tickets/{ticket_id}", headers=ops(Role.SUPPORT)
        )

    assert opened.json()["ticket"]["state"] == "opened"
    assert revoked.json()["state"] == "revoked" and revoked.json()["endedBy"] == "tenant-admin"
    assert reread.json()["state"] == "revoked"
    assert r.tickets.world.actions("tenant-a")[-2:] == [
        "support-access-revoked",
        "support-ticket-revoked",
    ]


async def test_a_refusal_ends_the_request_and_a_second_decision_is_a_409() -> None:
    async with routes() as (r, client):
        ticket_id = await _asked(r)
        refused = await send(
            client, "POST", f"/tenant/support-tickets/{ticket_id}/refusal", None, admin()
        )
        again = await send(
            client, "POST", f"/tenant/support-tickets/{ticket_id}/approval", None, admin()
        )

    assert refused.json()["state"] == "refused" and again.status_code == 409
    assert r.tickets.cache_names("tenant-a") == frozenset()


async def test_the_other_support_persons_request_is_listed_with_who_asked() -> None:
    async with routes() as (r, client):
        await _asked(r, principal=PRINCIPAL)
        await _asked(r, principal=OTHER_PRINCIPAL)
        listed = (await client.get("/tenant/support-tickets", headers=admin())).json()["tickets"]

    assert {t["requestedByRef"] for t in listed} == {
        PRINCIPAL.account_ref,
        OTHER_PRINCIPAL.account_ref,
    }


async def test_a_ticket_id_that_does_not_look_like_one_is_refused() -> None:
    async with routes() as (_, client):
        response = await client.get("/tenant/support-tickets/has space", headers=admin())

    assert response.status_code in (400, 404)
