"""The rules of the tenant configuration use cases (TEN-026): who may change it, how a draft is
built from the version in force, how a change is approved (one approver, or two who are not its
author when it touches a clinical setting, the DEC-032 pattern), and what the configuration says
about a tenant's readiness.

The storage behaviour (versions, the supersede, the two approvers over a real graph, two tenants)
is in tests/integration/application/test_tenant_config.py and
tests/integration/graph_store/test_tenant_config_repository.py, which run against a real Neo4j
(DEC-004). No in-memory configuration store is written here. Values are invented.
"""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.actor import Actor
from diucs.application.tenancy import ScopeId, TenantNotBound
from diucs.application.use_cases import tenant_config as use_cases
from diucs.application.use_cases.tenant_config import (
    CONFIGURATION_ROLES,
    ApproveConfigCommand,
    ApproveTenantConfig,
    BindDirectoryCommand,
    BindEntraDirectory,
    ConfigurationFacts,
    DraftConfigCommand,
    DraftTenantConfig,
    MapEntraGroup,
    MapGroupCommand,
    ReadTenantConfig,
    RecordChannelCommand,
    RecordContactCommand,
    RecordTenantChannel,
    RecordTenantContact,
    SetRetentionCommand,
    SetTenantRetention,
    apply_approval,
    check_configuration_role,
    configuration_facts,
    plan_binding,
    plan_channel,
    plan_draft,
    plan_mapping,
    plan_moves,
    plan_retention,
    supersede,
)
from diucs.domain.codes import Role
from diucs.domain.errors import Conflict, InvalidTransition, NotAllowed, ValidationFailed
from diucs.domain.model.tenant import (
    ConfigStatus,
    ContactKind,
    NumberStatus,
    RetentionClass,
    TenantConfig,
    TenantContact,
)
from diucs.domain.model.tenant_records import (
    BindingStatus,
    ChannelKind,
    ChannelProvider,
    EntraBinding,
    MappingStatus,
    RetentionAction,
    RoleMapping,
    TenantChannel,
    TenantRetention,
    default_retention,
)

NOW = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)
LATER = datetime(2026, 10, 29, 9, 30, tzinfo=UTC)
GUID = "11111111-2222-3333-4444-555555555555"
OTHER_GUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
SID = "AC" + "0" * 32
ADMIN_ROLES = frozenset({Role.OWNER})
# A reply window above the default needs the ladder moved with it (TEN-006's cross-field rule).
WINDOW = {
    "replyWindowMinutes": 45,
    "reminderAfterMinutes": 45,
    "phoneTaskAfterMinutes": 75,
    "escalateAfterMinutes": 105,
}


def actor(role: Role = Role.OWNER, practitioner_id: str | None = "prac-owner-1") -> Actor:
    return Actor(
        role=role,
        practitioner_id=practitioner_id,
        device_id=None,
        channel="web",
        service_ids=frozenset(),
    )


def command(**changes: Any) -> DraftConfigCommand:
    fields: dict[str, Any] = {"actor": actor(), "based_on": 0, "changes": dict(WINDOW)}
    fields.update(changes)
    return DraftConfigCommand(**fields)


def current_config(**values: Any) -> TenantConfig:
    return TenantConfig(
        version=1,
        status=ConfigStatus.CURRENT,
        values={**WINDOW, **values},
        created_at=NOW,
        created_by_ref="prac-lead-1",
        effective_from=NOW,
        approved_by_refs=("prac-owner-1", "prac-owner-2"),
    )


def draft_of(values: dict[str, Any], **changes: Any) -> TenantConfig:
    fields: dict[str, Any] = {
        "version": 2,
        "status": ConfigStatus.DRAFT,
        "values": values,
        "created_at": NOW,
        "created_by_ref": "prac-lead-1",
    }
    fields.update(changes)
    return TenantConfig(**fields)


# ---------------------------------------------------------------- who may configure


def test_no_role_may_configure_until_the_tenant_administrator_role_exists() -> None:
    """Fail closed (DEC-134 item 4): TEN-018 adds `tenant-admin`; the composition root then passes
    `frozenset({Role.TENANT_ADMIN})`. Until then the default holds no role."""
    assert frozenset() == CONFIGURATION_ROLES
    for role in Role:
        with pytest.raises(NotAllowed):
            check_configuration_role(actor(role), CONFIGURATION_ROLES)


def test_a_role_on_the_list_is_named_by_its_practitioner() -> None:
    assert (
        check_configuration_role(actor(Role.OWNER, "prac-owner-1"), ADMIN_ROLES) == "prac-owner-1"
    )


@pytest.mark.parametrize("role", [r for r in Role if r is not Role.OWNER])
def test_a_role_not_on_the_list_is_refused(role: Role) -> None:
    with pytest.raises(NotAllowed):
        check_configuration_role(actor(role), ADMIN_ROLES)


@pytest.mark.parametrize("practitioner", [None, "", "   "])
def test_an_actor_with_no_named_person_is_refused(practitioner: str | None) -> None:
    with pytest.raises(NotAllowed):
        check_configuration_role(actor(Role.OWNER, practitioner), ADMIN_ROLES)


def test_the_refusal_names_no_person_and_no_role() -> None:
    with pytest.raises(NotAllowed) as refused:
        check_configuration_role(actor(Role.ADVISOR, "prac-secret-9"), ADMIN_ROLES)

    assert "prac-secret-9" not in str(refused.value)
    assert "advisor" not in str(refused.value)


class _UnitOfWorkMustNotOpen:
    def __call__(self) -> Any:
        raise AssertionError("a refused command must not open a unit of work")


def _use_cases() -> list[tuple[Any, Any]]:
    uow = _UnitOfWorkMustNotOpen()
    clock = FixedClock(NOW)
    ids = SequentialIds()
    refused_actor = actor(Role.ADVISOR)
    return [
        (
            DraftTenantConfig(uow, clock, ADMIN_ROLES),
            DraftConfigCommand(refused_actor, 0, dict(WINDOW)),
        ),
        (ApproveTenantConfig(uow, clock, ADMIN_ROLES), ApproveConfigCommand(refused_actor, 2)),
        (
            RecordTenantContact(uow, clock, ADMIN_ROLES),
            RecordContactCommand(
                refused_actor, ContactKind.COORDINATION_PHONE, "Desk", "0300 123 4567"
            ),
        ),
        (
            RecordTenantChannel(uow, clock, ids, ADMIN_ROLES),
            RecordChannelCommand(
                refused_actor, ChannelKind.EMAIL, "Desk", from_address="a@b.example"
            ),
        ),
        (
            SetTenantRetention(uow, clock, ADMIN_ROLES),
            SetRetentionCommand(refused_actor, use_defaults=True),
        ),
        (BindEntraDirectory(uow, clock, ADMIN_ROLES), BindDirectoryCommand(refused_actor, GUID)),
        (MapEntraGroup(uow, clock, ADMIN_ROLES), MapGroupCommand(refused_actor, GUID, Role.LEAD)),
    ]


@pytest.mark.parametrize("index", range(7))
async def test_every_use_case_refuses_a_role_off_the_list_before_any_unit_of_work_opens(
    index: int,
) -> None:
    use_case, cmd = _use_cases()[index]

    with pytest.raises(NotAllowed):
        await use_case.execute(cmd)


@pytest.mark.parametrize("index", range(7))
async def test_every_use_case_refuses_everyone_when_it_is_built_with_the_default(
    index: int,
) -> None:
    use_case, cmd = _use_cases()[index]
    cmd = replace(cmd, actor=actor(Role.OWNER))
    default = type(use_case)(*_args_of(use_case))

    with pytest.raises(NotAllowed):
        await default.execute(cmd)


def _args_of(use_case: Any) -> tuple[Any, ...]:
    uow = _UnitOfWorkMustNotOpen()
    clock = FixedClock(NOW)
    if isinstance(use_case, RecordTenantChannel):
        return (uow, clock, SequentialIds())
    return (uow, clock)


# ---------------------------------------------------------------- a draft


def test_the_first_draft_is_built_from_nothing_and_needs_two_approvers() -> None:
    draft, diff = plan_draft(None, command(), version=1, now=NOW, author_ref="prac-lead-1")

    assert draft.version == 1
    assert draft.status is ConfigStatus.DRAFT
    assert dict(draft.values) == WINDOW
    assert draft.created_at == NOW
    assert draft.created_by_ref == "prac-lead-1"
    assert draft.approved_by_refs == ()
    assert draft.effective_from is None
    assert diff.changed_keys == tuple(sorted(WINDOW))
    assert diff.clinical_keys == tuple(sorted(WINDOW))
    assert diff.approvals_required == 2


def test_a_draft_keeps_what_is_in_force_and_changes_what_it_names() -> None:
    current = current_config(staleWarningHours=3, alertDefaultNotUpdatedHours=4)

    draft, diff = plan_draft(
        current,
        command(
            based_on=1,
            changes={"staleWarningHours": 1},
            removals=frozenset({"alertDefaultNotUpdatedHours"}),
        ),
        version=2,
        now=LATER,
        author_ref="prac-lead-1",
    )

    assert dict(draft.values) == {**WINDOW, "staleWarningHours": 1}
    assert diff.changed_keys == ("alertDefaultNotUpdatedHours", "staleWarningHours")
    assert diff.clinical_keys == ("staleWarningHours",)
    assert diff.approvals_required == 2


def test_an_operational_change_alone_needs_one_approver() -> None:
    draft, diff = plan_draft(
        current_config(),
        command(based_on=1, changes={"alertDefaultNotUpdatedHours": 4}),
        version=2,
        now=NOW,
        author_ref="prac-lead-1",
    )

    assert diff.clinical_keys == ()
    assert diff.approvals_required == 1
    assert draft.values["alertDefaultNotUpdatedHours"] == 4


def test_setting_a_key_back_to_its_default_is_still_a_change() -> None:
    current = current_config(staleWarningHours=3)

    draft, diff = plan_draft(
        current,
        command(based_on=1, changes={"staleWarningHours": 2}),
        version=2,
        now=NOW,
        author_ref="prac-lead-1",
    )

    assert draft.values["staleWarningHours"] == 2
    assert diff.changed_keys == ("staleWarningHours",)


def test_a_draft_built_on_a_version_that_is_no_longer_current_is_a_conflict() -> None:
    with pytest.raises(Conflict):
        plan_draft(
            current_config(),
            command(based_on=0),
            version=2,
            now=NOW,
            author_ref="prac-lead-1",
        )
    with pytest.raises(Conflict):
        plan_draft(None, command(based_on=3), version=1, now=NOW, author_ref="prac-lead-1")


@pytest.mark.parametrize(
    "cmd",
    [
        command(changes={}),
        command(changes={}, removals=frozenset()),
        command(changes={"replyWindowMinutes": 45}),
    ],
)
def test_a_draft_that_changes_nothing_is_refused(cmd: DraftConfigCommand) -> None:
    current = current_config()
    cmd = replace(cmd, based_on=1)

    with pytest.raises(ValidationFailed):
        plan_draft(current, cmd, version=2, now=NOW, author_ref="prac-lead-1")


@pytest.mark.parametrize(
    "cmd",
    [
        command(based_on=1, changes={"notASetting": 1}),
        command(based_on=1, changes={"staleWarningHours": 9}),
        command(based_on=1, changes={"staleWarningHours": "3"}),
        command(based_on=1, changes={"staleWarningHours": True}),
        command(based_on=1, changes={"replyWindowMinutes": 61}),
        command(based_on=1, changes={"replyWindowMinutes": 60}),  # the ladder no longer fits
        command(based_on=1, changes={}, removals=frozenset({"notASetting"})),
        command(based_on=1, changes={}, removals=frozenset({"staleWarningHours"})),  # not set
        command(
            based_on=1,
            changes={"staleWarningHours": 3},
            removals=frozenset({"staleWarningHours"}),
        ),
        command(based_on=1, changes={"systemName": "<b>"}),
        command(based_on=1, changes={"staleWarningHours": 3}, reason_code="has spaces"),
        command(based_on=1, changes={"staleWarningHours": 3}, reason_code="x" * 41),
    ],
)
def test_a_draft_that_breaks_a_setting_rule_is_refused_and_names_no_value(
    cmd: DraftConfigCommand,
) -> None:
    with pytest.raises(ValidationFailed) as refused:
        plan_draft(current_config(), cmd, version=2, now=NOW, author_ref="prac-lead-1")

    assert "has spaces" not in str(refused.value)


def test_a_draft_is_refused_with_a_naive_instant_or_an_unnamed_author() -> None:
    with pytest.raises(ValidationFailed):
        plan_draft(
            None, command(), version=1, now=datetime(2026, 10, 29, 9, 0), author_ref="prac-lead-1"
        )
    with pytest.raises(ValidationFailed):
        plan_draft(None, command(), version=1, now=NOW, author_ref="bad ref!")


def test_planning_a_draft_changes_neither_the_current_version_nor_the_command() -> None:
    current = current_config()
    cmd = command(based_on=1, changes={"staleWarningHours": 3})
    before = (dict(current.values), dict(cmd.changes))

    plan_draft(current, cmd, version=2, now=NOW, author_ref="prac-lead-1")

    assert (dict(current.values), dict(cmd.changes)) == before


def test_the_draft_version_number_is_the_one_given_and_must_be_a_whole_number_of_one_or_more() -> (
    None
):
    for bad in (0, -1, True, None):
        with pytest.raises(ValidationFailed):
            plan_draft(None, command(), version=bad, now=NOW, author_ref="prac-lead-1")  # type: ignore[arg-type]


# ---------------------------------------------------------------- approval


def test_one_approver_is_enough_for_an_operational_change_and_may_be_its_author() -> None:
    draft = draft_of({**WINDOW, "alertDefaultNotUpdatedHours": 4}, created_by_ref="prac-lead-1")

    approved = apply_approval(draft, current_config(), "prac-lead-1", LATER)

    assert approved.status is ConfigStatus.CURRENT
    assert approved.effective_from == LATER
    assert approved.approved_by_refs == ("prac-lead-1",)
    assert approved.values == draft.values
    assert approved.version == draft.version


def test_a_clinical_change_waits_for_a_second_approver() -> None:
    draft = draft_of({**WINDOW, "staleWarningHours": 3})

    first = apply_approval(draft, current_config(), "prac-owner-1", NOW)

    assert first.status is ConfigStatus.PENDING_APPROVAL
    assert first.approved_by_refs == ("prac-owner-1",)
    assert first.effective_from is None

    second = apply_approval(first, current_config(), "prac-owner-2", LATER)

    assert second.status is ConfigStatus.CURRENT
    assert second.approved_by_refs == ("prac-owner-1", "prac-owner-2")
    assert second.effective_from == LATER


def test_the_author_of_a_clinical_change_may_not_approve_it_first_or_second() -> None:
    draft = draft_of({**WINDOW, "staleWarningHours": 3}, created_by_ref="prac-lead-1")

    with pytest.raises(NotAllowed):
        apply_approval(draft, current_config(), "prac-lead-1", NOW)
    pending = apply_approval(draft, current_config(), "prac-owner-1", NOW)
    with pytest.raises(NotAllowed):
        apply_approval(pending, current_config(), "prac-lead-1", LATER)


def test_the_same_person_cannot_approve_twice() -> None:
    draft = draft_of({**WINDOW, "staleWarningHours": 3})
    pending = apply_approval(draft, current_config(), "prac-owner-1", NOW)

    with pytest.raises(NotAllowed, match="already approved"):
        apply_approval(pending, current_config(), "prac-owner-1", LATER)


@pytest.mark.parametrize("approver", ["", "   ", None, 5])
def test_an_approver_must_be_named(approver: Any) -> None:
    draft = draft_of({**WINDOW, "alertDefaultNotUpdatedHours": 4})

    with pytest.raises(NotAllowed):
        apply_approval(draft, current_config(), approver, NOW)


@pytest.mark.parametrize("status", [ConfigStatus.CURRENT, ConfigStatus.SUPERSEDED])
def test_a_version_that_is_in_force_or_past_cannot_be_approved(status: ConfigStatus) -> None:
    config = draft_of(
        {**WINDOW, "alertDefaultNotUpdatedHours": 4},
        status=status,
        effective_from=NOW,
        approved_by_refs=("prac-owner-1",),
    )

    with pytest.raises(InvalidTransition):
        apply_approval(config, current_config(), "prac-owner-2", LATER)


def test_the_approvals_needed_are_judged_against_what_is_in_force_now() -> None:
    """A draft whose only difference from the version in force is operational needs one approver,
    even if the draft was written against an older version: the snapshot is the whole truth."""
    in_force = current_config(staleWarningHours=3)
    draft = draft_of({**WINDOW, "staleWarningHours": 3, "alertDefaultNotUpdatedHours": 4})

    approved = apply_approval(draft, in_force, "prac-owner-1", NOW)

    assert approved.status is ConfigStatus.CURRENT


def test_the_first_version_always_needs_two_approvers_because_it_sets_clinical_values() -> None:
    draft = draft_of(dict(WINDOW), version=1)

    assert apply_approval(draft, None, "prac-owner-1", NOW).status is ConfigStatus.PENDING_APPROVAL


def test_an_approval_before_the_instant_is_known_is_refused() -> None:
    draft = draft_of({**WINDOW, "alertDefaultNotUpdatedHours": 4})

    with pytest.raises(ValidationFailed):
        apply_approval(draft, current_config(), "prac-owner-1", datetime(2026, 10, 29, 9, 0))


def test_a_superseded_version_keeps_everything_but_its_status() -> None:
    current = current_config(staleWarningHours=3)

    old = supersede(current)

    assert old.status is ConfigStatus.SUPERSEDED
    assert replace(old, status=ConfigStatus.CURRENT) == current


@pytest.mark.parametrize(
    "status", [ConfigStatus.DRAFT, ConfigStatus.PENDING_APPROVAL, ConfigStatus.SUPERSEDED]
)
def test_only_a_version_in_force_can_be_superseded(status: ConfigStatus) -> None:
    config = draft_of(dict(WINDOW), status=status)

    with pytest.raises(InvalidTransition):
        supersede(config)


# ---------------------------------------------------------------- a channel


def channel_command(**changes: Any) -> RecordChannelCommand:
    fields: dict[str, Any] = {
        "actor": actor(),
        "kind": ChannelKind.SMS,
        "sender_label": "Example capacity",
        "account_sid": SID,
        "secret_ref": "twilio/example-icb/auth-token",
    }
    fields.update(changes)
    return RecordChannelCommand(**fields)


def test_a_text_channel_takes_the_twilio_provider_and_the_id_it_is_given() -> None:
    channel = plan_channel(channel_command(), "ch-1", "example-icb")

    assert channel.id == "ch-1"
    assert channel.provider is ChannelProvider.TWILIO
    assert channel.status is NumberStatus.ACTIVE
    assert channel.kind is ChannelKind.SMS


def test_an_email_channel_takes_the_smtp_provider() -> None:
    channel = plan_channel(
        channel_command(
            kind=ChannelKind.EMAIL,
            account_sid=None,
            secret_ref=None,
            from_address="capacity@example.test",
        ),
        "ch-2",
        "example-icb",
    )

    assert channel.provider is ChannelProvider.SMTP


def test_a_channel_may_not_point_at_another_tenants_secret() -> None:
    with pytest.raises(ValidationFailed) as refused:
        plan_channel(
            channel_command(secret_ref="twilio/other-tenant/auth-token"), "ch-1", "example-icb"
        )

    assert "other-tenant" not in str(refused.value)


def test_a_channel_with_a_secret_reference_checks_it_against_the_bound_tenant() -> None:
    plan_channel(channel_command(secret_ref="twilio/example-icb/other-name"), "ch-1", "example-icb")
    with pytest.raises(ValidationFailed):
        plan_channel(channel_command(secret_ref="twilio/example-icb"), "ch-1", "example-icb")


def test_a_channel_keeps_the_status_it_is_given() -> None:
    channel = plan_channel(channel_command(status=NumberStatus.RETIRED), "ch-1", "example-icb")

    assert channel.status is NumberStatus.RETIRED


# ---------------------------------------------------------------- retention


def test_the_defaults_are_used_when_asked_for() -> None:
    assert plan_retention(SetRetentionCommand(actor(), use_defaults=True)) == default_retention()


def test_explicit_rules_are_used_as_they_are() -> None:
    rules = (
        TenantRetention(RetentionClass.BOOKINGS, 365, RetentionAction.DELETE),
        TenantRetention(RetentionClass.AUDIT_CHAIN, None, RetentionAction.KEEP),
    )

    assert plan_retention(SetRetentionCommand(actor(), rules=rules)) == rules


def _both() -> SetRetentionCommand:
    return SetRetentionCommand(actor(), rules=default_retention(), use_defaults=True)


def _twice() -> SetRetentionCommand:
    return SetRetentionCommand(
        actor(),
        rules=(
            TenantRetention(RetentionClass.BOOKINGS, 365, RetentionAction.DELETE),
            TenantRetention(RetentionClass.BOOKINGS, 730, RetentionAction.DELETE),
        ),
    )


def _a_string() -> SetRetentionCommand:
    return SetRetentionCommand(actor(), rules=("bookings",))  # type: ignore[arg-type]


def _a_list() -> SetRetentionCommand:
    rule = TenantRetention(RetentionClass.BOOKINGS, 1, RetentionAction.DELETE)
    return SetRetentionCommand(actor(), rules=[rule])  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "make",
    [
        lambda: SetRetentionCommand(actor()),
        _both,
        _twice,
        _a_string,
        _a_list,
    ],
    ids=["names-nothing", "both", "a-class-twice", "a-string", "a-list"],
)
def test_a_retention_command_that_names_nothing_both_or_a_class_twice_is_refused(
    make: Any,
) -> None:
    with pytest.raises(ValidationFailed):
        plan_retention(make())


# ---------------------------------------------------------------- directory binding


def test_a_first_binding_is_pending() -> None:
    assert plan_binding((), GUID) == (EntraBinding(GUID, BindingStatus.PENDING),)


@pytest.mark.parametrize("status", [BindingStatus.PENDING, BindingStatus.VERIFIED])
def test_binding_the_same_directory_again_changes_nothing(status: BindingStatus) -> None:
    existing = EntraBinding(
        GUID,
        status,
        NOW if status is BindingStatus.VERIFIED else None,
        "operator-1" if status is BindingStatus.VERIFIED else None,
    )

    assert plan_binding((existing,), GUID) == ()


def test_binding_another_directory_revokes_the_one_in_force() -> None:
    old = EntraBinding(GUID, BindingStatus.VERIFIED, NOW, "operator-1")

    planned = plan_binding((old,), OTHER_GUID)

    assert planned == (
        EntraBinding(GUID, BindingStatus.REVOKED),
        EntraBinding(OTHER_GUID, BindingStatus.PENDING),
    )


def test_a_revoked_directory_can_be_bound_again_as_pending() -> None:
    revoked = EntraBinding(GUID, BindingStatus.REVOKED)

    assert plan_binding((revoked,), GUID) == (EntraBinding(GUID, BindingStatus.PENDING),)


def test_a_revoked_binding_is_not_revoked_twice() -> None:
    revoked = EntraBinding(GUID, BindingStatus.REVOKED)

    assert plan_binding((revoked,), OTHER_GUID) == (
        EntraBinding(OTHER_GUID, BindingStatus.PENDING),
    )


@pytest.mark.parametrize("bad", ["", "not-a-guid", OTHER_GUID.upper(), None, 5])
def test_a_directory_id_that_is_not_a_guid_is_refused(bad: Any) -> None:
    with pytest.raises(ValidationFailed):
        plan_binding((), bad)


# ---------------------------------------------------------------- role mapping


def test_a_mapping_is_built_from_the_command() -> None:
    mapping = plan_mapping(MapGroupCommand(actor(), GUID, Role.CLINICAL))

    assert mapping == RoleMapping(GUID, Role.CLINICAL, MappingStatus.ACTIVE)
    retired = plan_mapping(MapGroupCommand(actor(), GUID, Role.CLINICAL, MappingStatus.RETIRED))
    assert retired.status is MappingStatus.RETIRED


@pytest.mark.parametrize("role", [Role.SUPPORT, Role.WALL, Role.REPORTER, Role.ANONYMOUS_LINK])
def test_a_group_cannot_be_mapped_to_a_role_the_directory_does_not_give(role: Role) -> None:
    with pytest.raises(ValidationFailed):
        plan_mapping(MapGroupCommand(actor(), GUID, role))


# ---------------------------------------------------------------- what the configuration says


def facts(**changes: Any) -> ConfigurationFacts:
    arguments: dict[str, Any] = {
        "current": None,
        "contacts": (),
        "channels": (),
        "retention": (),
        "bindings": (),
        "mappings": (),
    }
    arguments.update(changes)
    return configuration_facts(**arguments)


def test_an_empty_configuration_says_nothing_is_ready() -> None:
    assert facts() == ConfigurationFacts(
        config_approved=False,
        wording_complete=False,
        contact_kinds=frozenset(),
        retention_classes_set=frozenset(),
        role_mappings=0,
        entra_binding_verified=False,
        active_sms_channels=0,
        active_email_channels=0,
    )


def test_a_version_in_force_is_approved_and_complete_wording_is_read_from_it() -> None:
    wording = {
        "systemName": "Example capacity",
        "referralSystemName": "Example referrals",
        "coordinationTeamName": "Example team",
    }

    assert facts(current=current_config()).config_approved is True
    assert facts(current=current_config()).wording_complete is False
    assert facts(current=current_config(**wording)).wording_complete is True
    assert facts(current=current_config(systemName="Example capacity")).wording_complete is False


def test_contacts_retention_mappings_and_the_binding_are_counted_by_kind_and_status() -> None:
    contacts = (
        TenantContact(ContactKind.COORDINATION_PHONE, "Desk", "0300 123 4567"),
        TenantContact(ContactKind.SUPPORT_EMAIL, "Support", "support@example.test"),
    )
    retention = default_retention()[:3]
    mappings = (
        RoleMapping(GUID, Role.LEAD, MappingStatus.ACTIVE),
        RoleMapping(OTHER_GUID, Role.ADVISOR, MappingStatus.ACTIVE),
        RoleMapping("99999999-9999-9999-9999-999999999999", Role.OWNER, MappingStatus.RETIRED),
    )
    bindings = (
        EntraBinding(GUID, BindingStatus.REVOKED),
        EntraBinding(OTHER_GUID, BindingStatus.VERIFIED, NOW, "operator-1"),
    )

    result = facts(contacts=contacts, retention=retention, mappings=mappings, bindings=bindings)

    assert result.contact_kinds == {ContactKind.COORDINATION_PHONE, ContactKind.SUPPORT_EMAIL}
    assert result.retention_classes_set == {rule.data_class for rule in retention}
    assert result.role_mappings == 2
    assert result.entra_binding_verified is True


def test_a_pending_or_revoked_binding_is_not_verified() -> None:
    for status in (BindingStatus.PENDING, BindingStatus.REVOKED):
        assert facts(bindings=(EntraBinding(GUID, status),)).entra_binding_verified is False


def test_only_active_channels_count_and_each_kind_is_counted_apart() -> None:
    def make(channel_id: str, kind: ChannelKind, status: NumberStatus) -> TenantChannel:
        if kind is ChannelKind.SMS:
            return TenantChannel(
                id=channel_id,
                kind=kind,
                provider=ChannelProvider.TWILIO,
                status=status,
                sender_label="Example",
                account_sid=SID,
                secret_ref="twilio/example-icb/auth-token",
            )
        return TenantChannel(
            id=channel_id,
            kind=kind,
            provider=ChannelProvider.SMTP,
            status=status,
            sender_label="Example",
            from_address="capacity@example.test",
        )

    channels = (
        make("a", ChannelKind.SMS, NumberStatus.ACTIVE),
        make("b", ChannelKind.SMS, NumberStatus.RETIRED),
        make("c", ChannelKind.SMS, NumberStatus.QUARANTINED),
        make("d", ChannelKind.EMAIL, NumberStatus.ACTIVE),
        make("e", ChannelKind.EMAIL, NumberStatus.ACTIVE),
        make("f", ChannelKind.EMAIL, NumberStatus.RETIRED),
    )

    result = facts(channels=channels)

    assert (result.active_sms_channels, result.active_email_channels) == (1, 2)


def test_the_facts_hold_only_counts_kinds_and_flags() -> None:
    names = set(ConfigurationFacts.__dataclass_fields__)

    assert names == {
        "config_approved",
        "wording_complete",
        "contact_kinds",
        "retention_classes_set",
        "role_mappings",
        "entra_binding_verified",
        "active_sms_channels",
        "active_email_channels",
    }


def test_the_module_names_the_use_cases_the_plan_lists() -> None:
    for name in (
        "DraftTenantConfig",
        "ApproveTenantConfig",
        "RecordTenantContact",
        "RecordTenantChannel",
        "SetTenantRetention",
        "BindEntraDirectory",
        "MapEntraGroup",
        "ReadTenantConfig",
    ):
        assert hasattr(use_cases, name)


# ---------------------------------------------------------------- the moves of an approval


def test_a_change_completed_by_its_first_approver_passes_through_pending() -> None:
    draft = draft_of({**WINDOW, "alertDefaultNotUpdatedHours": 4})
    approved = apply_approval(draft, current_config(), "prac-owner-1", LATER)

    moves = plan_moves(draft, approved)

    assert [(m.status, expected) for m, expected in moves] == [
        (ConfigStatus.PENDING_APPROVAL, ConfigStatus.DRAFT),
        (ConfigStatus.CURRENT, ConfigStatus.PENDING_APPROVAL),
    ]
    assert moves[0][0].effective_from is None
    assert moves[1][0] == approved


def test_the_second_approver_of_a_clinical_change_is_one_move_from_pending() -> None:
    draft = draft_of({**WINDOW, "staleWarningHours": 3})
    pending = apply_approval(draft, current_config(), "prac-owner-1", NOW)
    approved = apply_approval(pending, current_config(), "prac-owner-2", LATER)

    assert plan_moves(pending, approved) == [(approved, ConfigStatus.PENDING_APPROVAL)]


def test_the_first_approver_of_a_clinical_change_is_one_move_from_draft() -> None:
    draft = draft_of({**WINDOW, "staleWarningHours": 3})
    pending = apply_approval(draft, current_config(), "prac-owner-1", NOW)

    assert plan_moves(draft, pending) == [(pending, ConfigStatus.DRAFT)]


# ---------------------------------------------------------------- the scope of a unit of work


class _UowOnScope:
    """A unit of work that has a scope and nothing else: reading a repository fails the test, so
    a refusal that comes first is proved by the test passing."""

    def __init__(self, scope: ScopeId | None) -> None:
        self._scope = scope

    @property
    def unit_scope(self) -> ScopeId | None:
        return self._scope

    @property
    def tenant_config(self) -> Any:
        raise AssertionError("the configuration was read before the scope was checked")

    async def __aenter__(self) -> _UowOnScope:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


def _on_scope(scope: ScopeId | None) -> Any:
    return lambda: _UowOnScope(scope)


def _scoped_use_cases(scope: ScopeId | None) -> list[tuple[Any, Any]]:
    uow = _on_scope(scope)
    clock = FixedClock(NOW)
    ids = SequentialIds()
    named = actor()
    return [
        (DraftTenantConfig(uow, clock, ADMIN_ROLES), DraftConfigCommand(named, 0, dict(WINDOW))),
        (ApproveTenantConfig(uow, clock, ADMIN_ROLES), ApproveConfigCommand(named, 2)),
        (
            RecordTenantContact(uow, clock, ADMIN_ROLES),
            RecordContactCommand(named, ContactKind.COORDINATION_PHONE, "Desk", "0300 123 4567"),
        ),
        (
            RecordTenantChannel(uow, clock, ids, ADMIN_ROLES),
            RecordChannelCommand(named, ChannelKind.EMAIL, "Desk", from_address="a@b.example"),
        ),
        (
            SetTenantRetention(uow, clock, ADMIN_ROLES),
            SetRetentionCommand(named, use_defaults=True),
        ),
        (BindEntraDirectory(uow, clock, ADMIN_ROLES), BindDirectoryCommand(named, GUID)),
        (MapEntraGroup(uow, clock, ADMIN_ROLES), MapGroupCommand(named, GUID, Role.LEAD)),
    ]


@pytest.mark.parametrize("index", range(7))
@pytest.mark.parametrize(
    "scope", [None, ScopeId.network("net-test")], ids=["no-scope", "network-scope"]
)
async def test_every_change_is_refused_in_no_scope_and_in_a_network_scope(
    index: int, scope: ScopeId | None
) -> None:
    use_case, cmd = _scoped_use_cases(scope)[index]

    with pytest.raises(TenantNotBound):
        await use_case.execute(cmd)


@pytest.mark.parametrize("read", ["policy", "wording", "contacts", "facts"])
@pytest.mark.parametrize(
    "scope", [None, ScopeId.network("net-test")], ids=["no-scope", "network-scope"]
)
async def test_every_read_is_refused_in_no_scope_and_in_a_network_scope(
    read: str, scope: ScopeId | None
) -> None:
    reader = ReadTenantConfig(_on_scope(scope))

    with pytest.raises(TenantNotBound):
        await getattr(reader, read)()
