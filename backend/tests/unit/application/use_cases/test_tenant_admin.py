"""The platform operator's tenant lifecycle (TEN-028, DEC-503): who may, in what order, what is
refused and what stops a half-finished step from doing harm.

No Neo4j: the directory and the registry are one recording fake over one set of tenants, and the
unit of work holds only the few repositories the use cases touch
(`tests/support/provisioning_fakes`).
What is stored on a real graph, with two tenants, is
`tests/integration/application/test_tenant_provisioning.py`.
"""

from typing import Any

import pytest

from diucs.application.actor import Actor
from diucs.application.tenancy import ScopeId, TenantMismatch, TenantNotBound
from diucs.application.use_cases import tenant_admin
from diucs.application.use_cases.tenant_admin import (
    ActivateTenant,
    ActivateTenantCommand,
    CreateTenant,
    CreateTenantCommand,
    MarkNumberTested,
    MarkNumberTestedCommand,
    RecordNumberCommand,
    RecordReferencesCommand,
    RecordTenantNumber,
    RecordTenantReferences,
    SetHostCommand,
    SetTenantHost,
    VerifyDirectoryCommand,
    VerifyEntraBinding,
)
from diucs.domain.codes import Role
from diucs.domain.errors import Conflict, NotAllowed, NotFound, ValidationFailed
from diucs.domain.model.tenant import OrganisationType, TenantStatus
from diucs.domain.model.tenant_records import BindingStatus
from tests.support.provisioning_fakes import (
    DIRECTORY_ID,
    NOW,
    OPERATOR,
    OTHER,
    TENANT,
    FakeHeads,
    FakePlatform,
    FakeWorld,
    FixedNow,
    operator,
    provisioning_tenant,
)
from tests.support.tenancy import as_tenant

SID = "AC" + "1" * 32
NUMBER = "+447700900123"


def _create(platform: FakePlatform, world: FakeWorld, heads: FakeHeads) -> CreateTenant:
    return CreateTenant(platform, platform, heads, world.factory(), FixedNow())  # type: ignore[arg-type]


def _command(actor: Actor | None = None, **fields: Any) -> CreateTenantCommand:
    base: dict[str, Any] = {
        "actor": operator() if actor is None else actor,
        "tenant_id": TENANT,
        "display_name": "New Organisation",
        "legal_name": "New Organisation Ltd",
        "organisation_type": OrganisationType.OTHER,
    }
    return CreateTenantCommand(**{**base, **fields})


# -- who may -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "role", [r for r in Role if r is not Role.PLATFORM_OPERATOR], ids=lambda r: r.value
)
async def test_only_the_platform_operator_runs_the_lifecycle(role: Role) -> None:
    platform, world, heads = FakePlatform(), FakeWorld(), FakeHeads()
    with as_tenant(TENANT), pytest.raises(NotAllowed):
        await _create(platform, world, heads).execute(_command(operator(role=role)))
    assert platform.calls == [] and heads.calls == [] and world.opened == 0


@pytest.mark.parametrize("ref", [None, "", "   "])
async def test_the_operator_must_be_named(ref: str | None) -> None:
    platform, world, heads = FakePlatform(), FakeWorld(), FakeHeads()
    with as_tenant(TENANT), pytest.raises(NotAllowed):
        await _create(platform, world, heads).execute(_command(operator(ref=ref)))
    assert platform.calls == [] and world.opened == 0


async def test_an_operator_of_another_tenant_is_refused_before_anything_is_read() -> None:
    platform, world, heads = FakePlatform(), FakeWorld(), FakeHeads()
    with as_tenant(TENANT), pytest.raises(TenantMismatch):
        await _create(platform, world, heads).execute(_command(operator(OTHER)))
    assert platform.calls == [] and world.opened == 0


async def test_with_no_tenant_bound_nothing_is_done() -> None:
    platform, world, heads = FakePlatform(), FakeWorld(), FakeHeads()
    with pytest.raises(TenantNotBound):
        await _create(platform, world, heads).execute(_command())
    assert platform.calls == []


# -- CreateTenant --------------------------------------------------------------------------------


async def test_a_tenant_is_created_in_provisioning_then_given_its_scope_then_audited() -> None:
    platform, world, heads = FakePlatform(), FakeWorld(), FakeHeads()

    with as_tenant(TENANT):
        result = await _create(platform, world, heads).execute(_command())

    assert result.created is True and result.tenant_id == TENANT
    created = platform.tenants[TENANT]
    assert created.status is TenantStatus.PROVISIONING and created.epoch == 1
    assert (
        created.hash_key_version == 1
    )  # its own keys: only the default tenant keeps the platform's
    assert platform.calls == [("create", TENANT)]
    assert [s.value for s in heads.calls if s is not None] == [TENANT]
    assert world.lists_ensured == 1
    assert world.audited() == ["CreateTenant"]
    assert world.audit[0].actor.role is Role.PLATFORM_OPERATOR
    assert world.audit[0].actor.practitioner_id == OPERATOR


async def test_the_id_to_create_must_be_the_scope_the_call_is_bound_to() -> None:
    platform, world, heads = FakePlatform(), FakeWorld(), FakeHeads()
    with as_tenant(TENANT), pytest.raises(ValidationFailed):
        await _create(platform, world, heads).execute(_command(tenant_id=OTHER))
    assert platform.calls == []


@pytest.mark.parametrize("bad", ["platform", "net-west", "A", "x" * 40, "has space"])
async def test_an_id_that_is_not_a_tenant_id_is_refused(bad: str) -> None:
    platform, world, heads = FakePlatform(), FakeWorld(), FakeHeads()
    with as_tenant(TENANT), pytest.raises(ValidationFailed):
        await _create(platform, world, heads).execute(_command(tenant_id=bad))
    assert platform.calls == []


async def test_a_creation_that_stopped_after_the_registry_is_finished_by_running_it_again() -> None:
    platform = FakePlatform(provisioning_tenant())
    world, heads = FakeWorld(), FakeHeads()

    with as_tenant(TENANT):
        result = await _create(platform, world, heads).execute(_command())

    assert result.created is False
    assert platform.calls == []  # the registry record is not written twice
    assert len(heads.calls) == 1 and world.lists_ensured == 1
    assert world.audit[0].snapshot["resumed"] is True


@pytest.mark.parametrize(
    "existing",
    [
        {"status": TenantStatus.ACTIVE, "activated_at": NOW},
        {"display_name": "Another Organisation"},
        {"legal_name": "Another Organisation Ltd"},
        {"organisation_type": OrganisationType.ICB},
        {"ods_code": "ABC12"},
    ],
    ids=["active", "name", "legal-name", "type", "ods"],
)
async def test_an_id_another_tenant_holds_is_a_conflict_and_nothing_is_written(
    existing: dict[str, Any],
) -> None:
    platform = FakePlatform(provisioning_tenant(**existing))
    world, heads = FakeWorld(), FakeHeads()

    with as_tenant(TENANT), pytest.raises(Conflict):
        await _create(platform, world, heads).execute(_command())

    assert platform.calls == [] and heads.calls == [] and world.opened == 0


# -- numbers, host, references -------------------------------------------------------------------


def _record_number(platform: FakePlatform, world: FakeWorld) -> RecordTenantNumber:
    return RecordTenantNumber(platform, platform, world.factory(), FixedNow())  # type: ignore[arg-type]


async def test_a_number_is_recorded_on_the_registry_first_and_then_as_the_tenants_channel() -> None:
    platform, world = FakePlatform(provisioning_tenant()), FakeWorld()

    with as_tenant(TENANT):
        channel_id = await _record_number(platform, world).execute(
            RecordNumberCommand(operator(), NUMBER, SID, "Sample sender")
        )

    assert platform.calls == [("put_number", (TENANT, NUMBER))]
    [channel] = world.config.channel_list
    assert channel.id == channel_id == "sms-447700900123"
    assert channel.secret_ref == f"twilio/{TENANT}/auth-token"  # the tenant's own reference
    assert world.audited() == ["RecordTenantNumber"]


async def test_a_number_another_tenant_holds_changes_nothing_of_this_tenants() -> None:
    from diucs.application.ports.outbound.tenant_registry import TenantNumberRecord

    platform = FakePlatform(provisioning_tenant(), provisioning_tenant(OTHER))
    platform.numbers_by_tenant[OTHER] = {
        NUMBER: TenantNumberRecord(NUMBER, SID, f"twilio/{OTHER}/auth-token")
    }
    world = FakeWorld()

    with as_tenant(TENANT), pytest.raises(Conflict):
        await _record_number(platform, world).execute(
            RecordNumberCommand(operator(), NUMBER, SID, "Sample sender")
        )

    assert world.config.channel_list == [] and world.opened == 0
    assert list(platform.numbers_by_tenant[OTHER]) == [NUMBER]


@pytest.mark.parametrize(
    ("number", "sid"), [("07700900123", SID), (NUMBER, "AC1"), ("", SID), (NUMBER, "")]
)
async def test_a_number_or_account_that_is_not_the_right_shape_is_refused(
    number: str, sid: str
) -> None:
    platform, world = FakePlatform(provisioning_tenant()), FakeWorld()
    with as_tenant(TENANT), pytest.raises(ValidationFailed):
        await _record_number(platform, world).execute(
            RecordNumberCommand(operator(), number, sid, "Sample sender")
        )
    assert platform.calls == []


async def test_a_tenant_that_has_left_takes_no_new_number() -> None:
    gone = provisioning_tenant(
        status=TenantStatus.OFFBOARDING, activated_at=NOW, offboarding_started_at=NOW
    )
    platform, world = FakePlatform(gone), FakeWorld()
    with as_tenant(TENANT), pytest.raises(NotAllowed):
        await _record_number(platform, world).execute(
            RecordNumberCommand(operator(), NUMBER, SID, "Sample sender")
        )
    assert platform.calls == []


async def test_a_number_for_a_tenant_nobody_created_is_not_found() -> None:
    platform, world = FakePlatform(), FakeWorld()
    with as_tenant(TENANT), pytest.raises(NotFound):
        await _record_number(platform, world).execute(
            RecordNumberCommand(operator(), NUMBER, SID, "Sample sender")
        )


async def test_a_test_text_is_marked_only_on_a_number_the_tenant_holds() -> None:
    platform, world = FakePlatform(provisioning_tenant()), FakeWorld()
    use_case = MarkNumberTested(platform, platform, world.factory(), FixedNow())  # type: ignore[arg-type]
    with as_tenant(TENANT):
        with pytest.raises(NotFound):
            await use_case.execute(MarkNumberTestedCommand(operator(), NUMBER))
        await _record_number(platform, world).execute(
            RecordNumberCommand(operator(), NUMBER, SID, "Sample sender")
        )
        await use_case.execute(MarkNumberTestedCommand(operator(), NUMBER))
    assert platform.numbers_by_tenant[TENANT][NUMBER].tested_at == NOW


def _set_host(platform: FakePlatform, world: FakeWorld) -> SetTenantHost:
    return SetTenantHost(platform, platform, world.factory(), FixedNow())  # type: ignore[arg-type]


async def test_the_host_is_set_in_its_lookup_form_and_audited() -> None:
    platform, world = FakePlatform(provisioning_tenant()), FakeWorld()
    with as_tenant(TENANT):
        await _set_host(platform, world).execute(SetHostCommand(operator(), "New-Org.Example.ORG"))
    assert platform.hosts == {TENANT: "new-org.example.org"}
    assert world.audited() == ["SetTenantHost"]


async def test_a_host_another_tenant_holds_is_a_conflict_before_anything_is_audited() -> None:
    platform = FakePlatform(provisioning_tenant(), provisioning_tenant(OTHER))
    platform.hosts[OTHER] = "shared.example.org"
    world = FakeWorld()
    with as_tenant(TENANT), pytest.raises(Conflict):
        await _set_host(platform, world).execute(SetHostCommand(operator(), "shared.example.org"))
    assert world.audit == [] and TENANT not in platform.hosts


@pytest.mark.parametrize("bad", ["", "not a host", "https://a.example.org", "a_b.example"])
async def test_a_host_that_is_not_a_host_name_is_refused(bad: str) -> None:
    platform, world = FakePlatform(provisioning_tenant()), FakeWorld()
    with as_tenant(TENANT), pytest.raises(ValidationFailed):
        await _set_host(platform, world).execute(SetHostCommand(operator(), bad))
    assert platform.calls == []


def _references(platform: FakePlatform, world: FakeWorld) -> RecordTenantReferences:
    return RecordTenantReferences(platform, platform, world.factory(), FixedNow())  # type: ignore[arg-type]


async def test_references_are_saved_with_a_compare_and_set_on_the_record_as_read() -> None:
    platform, world = FakePlatform(provisioning_tenant()), FakeWorld()
    with as_tenant(TENANT):
        recorded = await _references(platform, world).execute(
            RecordReferencesCommand(operator(), dsa_ref="DSA-001", dcb0160_ref="CS-9")
        )
    assert recorded == ("dcb0160_ref", "dsa_ref")
    assert platform.calls == [
        ("save", (TENANT, 1, TenantStatus.PROVISIONING, TenantStatus.PROVISIONING))
    ]
    stored = platform.tenants[TENANT]
    assert (stored.dsa_ref, stored.dpia_ref, stored.dcb0160_ref) == ("DSA-001", None, "CS-9")
    assert world.audit[0].snapshot == {"recorded": ["dcb0160_ref", "dsa_ref"]}


async def test_a_second_call_keeps_the_references_the_first_recorded() -> None:
    platform, world = FakePlatform(provisioning_tenant(dsa_ref="DSA-001")), FakeWorld()
    with as_tenant(TENANT):
        await _references(platform, world).execute(
            RecordReferencesCommand(operator(), dpia_ref="DP-2")
        )
    assert (platform.tenants[TENANT].dsa_ref, platform.tenants[TENANT].dpia_ref) == (
        "DSA-001",
        "DP-2",
    )


async def test_no_reference_at_all_and_a_reference_that_is_free_text_are_refused() -> None:
    platform, world = FakePlatform(provisioning_tenant()), FakeWorld()
    with as_tenant(TENANT):
        with pytest.raises(ValidationFailed):
            await _references(platform, world).execute(RecordReferencesCommand(operator()))
        with pytest.raises(ValidationFailed):
            await _references(platform, world).execute(
                RecordReferencesCommand(operator(), dsa_ref="<script>alert(1)</script>")
            )
    assert platform.calls == []


async def test_a_record_that_moved_since_it_was_read_is_a_conflict() -> None:
    platform, world = FakePlatform(provisioning_tenant()), FakeWorld()
    platform.reject_save = True
    with as_tenant(TENANT), pytest.raises(Conflict):
        await _references(platform, world).execute(
            RecordReferencesCommand(operator(), dsa_ref="D-1")
        )
    assert world.audit == []


# -- the directory -------------------------------------------------------------------------------


def _verify(platform: FakePlatform, world: FakeWorld) -> VerifyEntraBinding:
    return VerifyEntraBinding(platform, platform, world.factory(), FixedNow())  # type: ignore[arg-type]


async def test_a_waiting_binding_is_verified_by_the_named_operator_and_the_registry_holds_it() -> (
    None
):
    platform, world = FakePlatform(provisioning_tenant()), FakeWorld()
    world.config.make_ready()
    with as_tenant(TENANT):
        await _verify(platform, world).execute(VerifyDirectoryCommand(operator(), DIRECTORY_ID))
    [binding] = world.config.binding_list
    assert binding.status is BindingStatus.VERIFIED
    assert binding.verified_by_ref == OPERATOR and binding.verified_at == NOW
    assert platform.directories == {TENANT: DIRECTORY_ID}
    assert world.audited() == ["VerifyEntraBinding"]


async def test_a_directory_nobody_bound_cannot_be_verified() -> None:
    platform, world = FakePlatform(provisioning_tenant()), FakeWorld()
    with as_tenant(TENANT), pytest.raises(NotFound):
        await _verify(platform, world).execute(VerifyDirectoryCommand(operator(), DIRECTORY_ID))
    assert platform.directories == {}


async def test_a_directory_another_tenant_holds_is_a_conflict_and_the_binding_stays_pending() -> (
    None
):
    platform = FakePlatform(provisioning_tenant(), provisioning_tenant(OTHER))
    platform.directories[OTHER] = DIRECTORY_ID
    world = FakeWorld()
    world.config.make_ready()
    with as_tenant(TENANT), pytest.raises(Conflict):
        await _verify(platform, world).execute(VerifyDirectoryCommand(operator(), DIRECTORY_ID))
    assert world.config.binding_list[0].status is BindingStatus.PENDING


async def test_a_directory_id_that_is_not_a_directory_id_is_refused() -> None:
    platform, world = FakePlatform(provisioning_tenant()), FakeWorld()
    with as_tenant(TENANT), pytest.raises(ValidationFailed):
        await _verify(platform, world).execute(VerifyDirectoryCommand(operator(), "not-a-guid"))


# -- ActivateTenant ------------------------------------------------------------------------------


class _Ids:
    def new_id(self) -> str:
        return "id-1"


def _activate(
    platform: FakePlatform, world: FakeWorld, area: set[str] | None = None
) -> ActivateTenant:
    districts = frozenset({"DT1", "DT2"} if area is None else area)
    return ActivateTenant(
        platform,
        platform,
        world.factory(),
        _Ids(),
        FixedNow(),
        lambda scope: districts,  # type: ignore[arg-type]
    )


async def _ready(platform: FakePlatform, world: FakeWorld) -> None:
    """Everything an activation needs: configuration, a tested number, references, a host and an
    open invitation."""
    from diucs.application.ports.outbound.tenant_registry import TenantNumberRecord
    from diucs.application.provisioning import TENANT_ADMIN_INVITE

    world.config.make_ready()
    world.config.binding_list = [
        b.__class__(b.directory_id, BindingStatus.VERIFIED, NOW, OPERATOR)
        for b in world.config.binding_list
    ]
    platform.tenants[TENANT] = provisioning_tenant(dsa_ref="D-1", dpia_ref="P-1", dcb0160_ref="C-1")
    platform.hosts[TENANT] = "new-org.example.org"
    platform.numbers_by_tenant[TENANT] = {
        NUMBER: TenantNumberRecord(NUMBER, SID, f"twilio/{TENANT}/auth-token", tested_at=NOW)
    }
    world.tokens.open_about[(TENANT_ADMIN_INVITE, f"tenant-admin-{TENANT}")] = object()


@pytest.fixture
def seeded(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """`seed_recurring_work` opens units of its own and is proved by its own tests: here it only
    records that it ran, for the tenant that was bound."""
    ran: list[str] = []

    async def fake(factory: Any, ids: Any, clock: Any) -> tuple[bool, bool]:
        from diucs.application.tenancy import current_tenant

        ran.append(current_tenant())
        return True, True

    monkeypatch.setattr(tenant_admin, "seed_recurring_work", fake)
    return ran


async def test_a_ready_tenant_is_activated_once_judged_and_seeded(seeded: list[str]) -> None:
    platform, world = FakePlatform(), FakeWorld()
    await _ready(platform, world)

    with as_tenant(TENANT):
        result = await _activate(platform, world).execute(ActivateTenantCommand(operator()))

    assert result.tenant_id == TENANT and result.epoch == 1 and result.seeded == (True, True)
    assert platform.tenants[TENANT].status is TenantStatus.ACTIVE
    assert platform.tenants[TENANT].activated_at == NOW
    # One compare and set, on the epoch and status as read.
    assert platform.calls == [("save", (TENANT, 1, TenantStatus.PROVISIONING, TenantStatus.ACTIVE))]
    assert world.audited() == ["ActivateTenant"]
    assert seeded == [TENANT]


async def test_a_tenant_with_nothing_set_lists_every_blocker_in_fixed_words_and_changes_nothing(
    seeded: list[str],
) -> None:
    platform, world = FakePlatform(provisioning_tenant()), FakeWorld()

    with as_tenant(TENANT), pytest.raises(NotAllowed) as refused:
        await _activate(platform, world, area=set()).execute(ActivateTenantCommand(operator()))

    text = str(refused.value)
    for blocker in (
        "Configuration version approved",
        "At least one sender number active with a test text delivered",
        "First tenant administrator invited",
        "Sign-in directory bound and verified",
        "At least one role mapping",
        "Support contacts set",
        "Retention set for every data class",
        "references recorded",
        "System, referral system and coordination team names set",
        "Area districts set",
        "Host set",
    ):
        assert blocker in text, blocker
    assert TENANT not in text and "New Organisation" not in text
    assert platform.calls == [] and world.audit == [] and seeded == []
    assert platform.tenants[TENANT].status is TenantStatus.PROVISIONING


@pytest.mark.parametrize(
    ("break_it", "blocker"),
    [
        (lambda p, w: p.hosts.pop(TENANT), "Host set"),
        (lambda p, w: p.numbers_by_tenant[TENANT].clear(), "test text delivered"),
        (lambda p, w: w.tokens.open_about.clear(), "First tenant administrator invited"),
        (lambda p, w: setattr(w.config, "current", None), "Configuration version approved"),
        (lambda p, w: setattr(w.config, "binding_list", []), "Sign-in directory bound"),
        (lambda p, w: setattr(w.config, "mapping_list", []), "role mapping"),
    ],
    ids=["host", "number", "invitation", "configuration", "directory", "mapping"],
)
async def test_each_missing_thing_alone_blocks_activation(
    break_it: Any, blocker: str, seeded: list[str]
) -> None:
    platform, world = FakePlatform(), FakeWorld()
    await _ready(platform, world)
    break_it(platform, world)

    with as_tenant(TENANT), pytest.raises(NotAllowed, match=blocker):
        await _activate(platform, world).execute(ActivateTenantCommand(operator()))

    assert platform.tenants[TENANT].status is TenantStatus.PROVISIONING
    assert world.audit == [] and seeded == []


async def test_a_number_that_has_not_delivered_a_test_text_does_not_count(
    seeded: list[str],
) -> None:
    from dataclasses import replace

    platform, world = FakePlatform(), FakeWorld()
    await _ready(platform, world)
    held = platform.numbers_by_tenant[TENANT]
    held[NUMBER] = replace(held[NUMBER], tested_at=None)

    with as_tenant(TENANT), pytest.raises(NotAllowed, match="test text delivered"):
        await _activate(platform, world).execute(ActivateTenantCommand(operator()))


async def test_a_record_that_moved_between_the_read_and_the_write_is_a_conflict(
    seeded: list[str],
) -> None:
    platform, world = FakePlatform(), FakeWorld()
    await _ready(platform, world)
    platform.reject_save = True

    with as_tenant(TENANT), pytest.raises(Conflict):
        await _activate(platform, world).execute(ActivateTenantCommand(operator()))

    assert world.audit == [] and seeded == []


@pytest.mark.parametrize("status", [TenantStatus.ACTIVE, TenantStatus.SUSPENDED])
async def test_only_a_provisioning_tenant_is_activated(
    status: TenantStatus, seeded: list[str]
) -> None:
    extra: dict[str, Any] = {"activated_at": NOW}
    if status is TenantStatus.SUSPENDED:
        from diucs.domain.model.tenant import SuspendMode, SuspendReason

        extra |= {
            "suspended_at": NOW,
            "suspend_mode": SuspendMode.BLOCKED,
            "suspend_reason": SuspendReason.CONTRACT,
        }
    platform = FakePlatform(provisioning_tenant(status=status, **extra))
    world = FakeWorld()
    with as_tenant(TENANT), pytest.raises(NotAllowed):
        await _activate(platform, world).execute(ActivateTenantCommand(operator()))
    assert platform.calls == [] and seeded == []


async def test_a_tenant_nobody_created_is_not_found(seeded: list[str]) -> None:
    platform, world = FakePlatform(), FakeWorld()
    with as_tenant(TENANT), pytest.raises(NotFound):
        await _activate(platform, world).execute(ActivateTenantCommand(operator()))


async def test_assess_writes_nothing_and_names_what_is_missing() -> None:
    platform, world = FakePlatform(provisioning_tenant()), FakeWorld()
    with as_tenant(TENANT):
        assessment = await _activate(platform, world).assess(operator())
    assert "Host set" in assessment.blockers
    assert platform.calls == [] and world.audit == [] and world.commits == 0


def test_the_scope_helper_names_the_tenant_scope() -> None:
    assert ScopeId.tenant(TENANT).value == TENANT
