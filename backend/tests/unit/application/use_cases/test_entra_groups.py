"""The organisation's Entra groups and their members (DEC-1317): the operator's set-up and the
tenant administrator's changes.

No Neo4j and no network: a fake directory (`FakeEntraGroups`) behind the port, the provisioning
fakes for the unit of work, and an in-memory invite store. What is proved: the groups are named from
the prefix (ODS code, else the tenant id) and nothing else is ever made; making them again changes
nothing; each is assigned to our app role on the organisation's service principal and mapped to its
role in our graph (the administrators' group to the tenant administrator, never the platform
operator); a person who is not found is refused; the tenant administrator can change only groups our
own mappings name and the directory's own name for which starts with the prefix; and every change is
audited with the actor and the group id and never an address.
"""

import json
from dataclasses import replace
from datetime import datetime
from typing import Any

import pytest

from overwatch.adapters.testing.fake_entra_groups import FakeEntraGroups
from overwatch.adapters.testing.fixed_secrets import FixedSecretStore
from overwatch.application.ports.outbound.admin_consent import AppInstallation, GraphUnavailable
from overwatch.application.ports.outbound.entra_groups import GroupMissing, InviteNotPermitted
from overwatch.application.ports.outbound.tokens import LINK_TOKEN_SECRET
from overwatch.application.use_cases.entra_groups import (
    AddInitialGroupMember,
    AddInitialMemberCommand,
    ChangeGroupMember,
    ChangeMemberCommand,
    ProvisionEntraGroups,
    ProvisionEntraGroupsCommand,
    ReadManagedGroups,
    SearchDirectoryPeople,
)
from overwatch.domain.codes import Role
from overwatch.domain.errors import Conflict, NotAllowed, ValidationFailed
from overwatch.domain.model.tenant_records import MappingStatus, RoleMapping
from overwatch.domain.rules.admin_consent import (
    AdminConsentInvite,
    InviteStatus,
    hash_email,
)
from overwatch.domain.rules.entra_groups import OVERWATCH_MEMBER_APP_ROLE_ID
from tests.support.provisioning_fakes import (
    DIRECTORY_ID,
    NOW,
    OTHER,
    TENANT,
    FakePlatform,
    FakeUnit,
    FakeWorld,
    FixedNow,
    operator,
    provisioning_tenant,
)
from tests.support.tenancy import as_tenant

SECRET = b"test-only-link-token-secret-0123456789"
SP_ID = "22222222-2222-4222-8222-222222222222"
ODS = "F81044"
PREFIX = f"{ODS}_overwatch_"
JANE = "Jane.Member@Example-Trust.test"
SAM = "sam.second@example-trust.test"
STAFF_GROUP_ID = "bbbbbbbb-0000-4000-8000-00000000cafe"  # a group the organisation made itself


class _Consents:
    def __init__(self) -> None:
        self.by_tenant: dict[str, list[AdminConsentInvite]] = {}
        self.scope = ""

    def _mine(self) -> list[AdminConsentInvite]:
        return self.by_tenant.setdefault(self.scope, [])

    async def consented(self) -> AdminConsentInvite | None:
        done = [i for i in self._mine() if i.status is InviteStatus.CONSENTED]
        return max(done, key=lambda i: i.consented_at or i.created_at, default=None)

    async def set_service_principal(self, invite_id: str, service_principal_id: str) -> None:
        for index, invite in enumerate(self._mine()):
            if invite.invite_id == invite_id:
                self._mine()[index] = replace(invite, service_principal_id=service_principal_id)


class _Installation:
    def __init__(self, result: AppInstallation | Exception) -> None:
        self.result = result
        self.asked: list[str] = []

    async def check(self, directory_id: str) -> AppInstallation:
        self.asked.append(directory_id)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _invite(status: InviteStatus, sp: str | None = SP_ID) -> AdminConsentInvite:
    consented = status is InviteStatus.CONSENTED
    return AdminConsentInvite(
        invite_id="inv-1",
        directory_id=DIRECTORY_ID,
        email_hash="a" * 64,
        email_masked="j***@example.org",
        state_hash="b" * 64,
        status=status,
        created_at=NOW,
        expires_at=datetime(2026, 11, 6, 9, 0, tzinfo=NOW.tzinfo),
        consented_at=NOW if consented else None,
        service_principal_id=sp if consented else None,
    )


class _Rig:
    def __init__(
        self,
        *,
        tenant_id: str = TENANT,
        ods: str | None = ODS,
        consent: InviteStatus | None = InviteStatus.CONSENTED,
        sp: str | None = SP_ID,
        directory: FakeEntraGroups | None = None,
        installation: AppInstallation | Exception | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.platform = FakePlatform(provisioning_tenant(tenant_id, ods_code=ods))
        self.world = FakeWorld()
        self.consents = _Consents()
        self.directory = directory or FakeEntraGroups()
        self.installation = _Installation(
            installation or AppInstallation(True, service_principal_id=SP_ID)
        )
        self.clock = FixedNow()
        self.secrets = FixedSecretStore({LINK_TOKEN_SECRET: SECRET})
        if consent is not None:
            self.consents.by_tenant[tenant_id] = [_invite(consent, sp)]

    def factory(self) -> Any:
        from overwatch.application.tenancy import current_scope_or_none

        def make() -> FakeUnit:
            scope = current_scope_or_none()
            unit = FakeUnit(self.world, scope)
            self.consents.scope = "" if scope is None else scope.value
            unit.admin_consents = self.consents  # type: ignore[attr-defined]
            return unit

        return make

    def provision(self) -> ProvisionEntraGroups:
        return ProvisionEntraGroups(
            self.platform,  # type: ignore[arg-type]
            self.factory(),
            self.clock,
            self.directory,
            self.installation,
        )

    def first_member(self) -> AddInitialGroupMember:
        return AddInitialGroupMember(
            self.platform,  # type: ignore[arg-type]
            self.factory(),
            self.clock,
            self.directory,
            self.secrets,
        )

    def reader(self) -> ReadManagedGroups:
        return ReadManagedGroups(self.platform, self.factory(), self.directory)  # type: ignore[arg-type]

    def searcher(self) -> SearchDirectoryPeople:
        return SearchDirectoryPeople(self.platform, self.factory(), self.directory)  # type: ignore[arg-type]

    def changer(self) -> ChangeGroupMember:
        return ChangeGroupMember(
            self.platform,  # type: ignore[arg-type]
            self.factory(),
            self.clock,
            self.directory,
            self.secrets,
        )

    def admin(self, ref: str = "admin-ref-1") -> Any:
        return operator(self.tenant_id, ref, Role.TENANT_ADMIN)

    def ops(self) -> Any:
        return operator(self.tenant_id)

    async def provisioned(self, *roles: Role) -> dict[Role, str]:
        with as_tenant(self.tenant_id):
            made = await self.provision().execute(ProvisionEntraGroupsCommand(self.ops(), roles))
        return {g.role: g.group_id for g in made}

    def mappings(self) -> dict[str, Role]:
        return {m.group_object_id: m.role for m in self.world.config.mapping_list}


# ------------------------------------------------------------------ the operator: the groups


async def test_the_groups_are_named_from_the_ods_prefix_and_made_as_the_directory_sees_them() -> (
    None
):
    rig = _Rig()
    with as_tenant(TENANT):
        made = await rig.provision().execute(
            ProvisionEntraGroupsCommand(rig.ops(), (Role.LEAD, Role.CLINICAL))
        )

    assert [g.name for g in made] == [
        "F81044_overwatch_tenant-admin",
        "F81044_overwatch_lead",
        "F81044_overwatch_clinical",
    ]
    assert all(g.created and g.assigned for g in made)
    names = set(rig.directory.groups[DIRECTORY_ID].values())
    assert names == {g.name for g in made}
    assert all(name.startswith(PREFIX) for name in names)


async def test_a_tenant_with_no_ods_code_is_named_from_its_tenant_id() -> None:
    rig = _Rig(ods=None)
    with as_tenant(TENANT):
        made = await rig.provision().execute(ProvisionEntraGroupsCommand(rig.ops(), (Role.LEAD,)))
    assert [g.name for g in made] == [
        f"{TENANT}_overwatch_tenant-admin",
        f"{TENANT}_overwatch_lead",
    ]


async def test_the_administrators_group_is_always_made_even_with_no_roles_asked_for() -> None:
    rig = _Rig()
    ids = await rig.provisioned()
    assert list(ids) == [Role.TENANT_ADMIN]


async def test_each_group_is_assigned_to_our_app_role_on_the_organisations_service_principal() -> (
    None
):
    rig = _Rig()
    ids = await rig.provisioned(Role.LEAD)

    assert rig.directory.assignments == {
        (DIRECTORY_ID, SP_ID, group_id, OVERWATCH_MEMBER_APP_ROLE_ID) for group_id in ids.values()
    }
    assert OVERWATCH_MEMBER_APP_ROLE_ID == "52475a88-b5cd-4e30-9090-316d1c29672f"


async def test_each_group_is_mapped_to_its_role_and_the_administrators_to_tenant_admin() -> None:
    rig = _Rig()
    ids = await rig.provisioned(Role.LEAD, Role.ADVISOR)

    assert rig.mappings() == {
        ids[Role.TENANT_ADMIN]: Role.TENANT_ADMIN,
        ids[Role.LEAD]: Role.LEAD,
        ids[Role.ADVISOR]: Role.ADVISOR,
    }
    assert Role.PLATFORM_OPERATOR not in rig.mappings().values()
    assert all(m.status is MappingStatus.ACTIVE for m in rig.world.config.mapping_list)
    assert rig.world.audited() == ["ProvisionEntraGroups"] and rig.world.commits == 1


async def test_making_the_groups_again_changes_nothing() -> None:
    rig = _Rig()
    first = await rig.provisioned(Role.LEAD)
    before = dict(rig.directory.groups[DIRECTORY_ID])
    with as_tenant(TENANT):
        again = await rig.provision().execute(ProvisionEntraGroupsCommand(rig.ops(), (Role.LEAD,)))

    assert {g.role: g.group_id for g in again} == first
    assert not any(g.created or g.assigned for g in again)
    assert rig.directory.groups[DIRECTORY_ID] == before  # no second group of either name
    assert len(rig.world.config.mapping_list) == 2


async def test_a_group_that_already_has_the_name_is_reused_not_made_again() -> None:
    directory = FakeEntraGroups()
    existing = await directory.create_group(DIRECTORY_ID, "F81044_overwatch_lead", "made by hand")
    rig = _Rig(directory=directory)
    ids = await rig.provisioned(Role.LEAD)

    assert ids[Role.LEAD] == existing
    assert list(directory.groups[DIRECTORY_ID].values()).count("F81044_overwatch_lead") == 1


@pytest.mark.parametrize(
    "role", [Role.PLATFORM_OPERATOR, Role.NETWORK_ADMIN, Role.TENANT_ADMIN, Role.SUPPORT, Role.WALL]
)
async def test_a_role_with_no_group_is_refused_before_any_call(role: Role) -> None:
    rig = _Rig()
    with as_tenant(TENANT), pytest.raises(ValidationFailed):
        await rig.provision().execute(ProvisionEntraGroupsCommand(rig.ops(), (role,)))
    assert rig.directory.calls == [] and rig.world.commits == 0


@pytest.mark.parametrize(
    "role", [r for r in Role if r is not Role.PLATFORM_OPERATOR], ids=lambda r: r.value
)
async def test_only_the_platform_operator_makes_the_groups(role: Role) -> None:
    rig = _Rig()
    with as_tenant(TENANT), pytest.raises(NotAllowed):
        await rig.provision().execute(
            ProvisionEntraGroupsCommand(operator(TENANT, role=role), (Role.LEAD,))
        )
    assert rig.directory.calls == []


@pytest.mark.parametrize("consent", [None, InviteStatus.PENDING])
async def test_nothing_is_made_until_the_administrator_has_consented(
    consent: InviteStatus | None,
) -> None:
    rig = _Rig(consent=consent)
    with as_tenant(TENANT), pytest.raises(NotAllowed):
        await rig.provision().execute(ProvisionEntraGroupsCommand(rig.ops(), (Role.LEAD,)))
    assert rig.directory.calls == [] and rig.world.config.mapping_list == []


async def test_another_tenants_consent_is_not_used() -> None:
    rig = _Rig(tenant_id=OTHER, consent=None)
    rig.consents.by_tenant[TENANT] = [_invite(InviteStatus.CONSENTED)]  # consent of another tenant
    with as_tenant(OTHER), pytest.raises(NotAllowed):
        await rig.provision().execute(ProvisionEntraGroupsCommand(operator(OTHER), (Role.LEAD,)))
    assert rig.directory.calls == []


async def test_a_consent_given_before_the_principal_was_kept_reads_it_again_and_keeps_it() -> None:
    rig = _Rig(sp=None, installation=AppInstallation(True, service_principal_id=SP_ID))
    ids = await rig.provisioned()

    assert rig.installation.asked == [DIRECTORY_ID]
    assert rig.consents.by_tenant[TENANT][0].service_principal_id == SP_ID
    assert (DIRECTORY_ID, SP_ID, ids[Role.TENANT_ADMIN], OVERWATCH_MEMBER_APP_ROLE_ID) in (
        rig.directory.assignments
    )


async def test_an_app_that_is_not_installed_makes_nothing() -> None:
    rig = _Rig(sp=None, installation=AppInstallation(False, reason="gone"))
    with as_tenant(TENANT), pytest.raises(NotAllowed):
        await rig.provision().execute(ProvisionEntraGroupsCommand(rig.ops(), ()))
    assert rig.directory.calls == []


async def test_a_group_that_already_gives_another_role_is_never_remapped() -> None:
    rig = _Rig()
    ids = await rig.provisioned(Role.LEAD)
    rig.world.config.mapping_list = [
        RoleMapping(ids[Role.LEAD], Role.CLINICAL, MappingStatus.ACTIVE)
    ]
    commits = rig.world.commits
    with as_tenant(TENANT), pytest.raises(Conflict):
        await rig.provision().execute(ProvisionEntraGroupsCommand(rig.ops(), (Role.LEAD,)))
    assert rig.world.config.mapping_list[0].role is Role.CLINICAL
    assert rig.world.commits == commits


async def test_when_the_directory_fails_half_way_nothing_is_mapped_and_a_rerun_finishes() -> None:
    rig = _Rig()
    real = rig.directory.assign_app_role
    calls = 0

    async def flaky(*args: str) -> bool:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise GraphUnavailable("throttled")
        return await real(*args)

    rig.directory.assign_app_role = flaky  # type: ignore[method-assign]
    with as_tenant(TENANT), pytest.raises(GraphUnavailable):
        await rig.provision().execute(ProvisionEntraGroupsCommand(rig.ops(), (Role.LEAD,)))
    assert rig.world.config.mapping_list == [] and rig.world.commits == 0

    rig.directory.assign_app_role = real  # type: ignore[method-assign]
    ids = await rig.provisioned(Role.LEAD)
    assert set(rig.mappings()) == set(ids.values())
    assert (
        len(rig.directory.groups[DIRECTORY_ID]) == 2
    )  # the group made before the failure is reused


# ------------------------------------------------------------------ the operator: first members


def _first(group: Role, email: str = JANE, **actor: Any) -> AddInitialMemberCommand:
    return AddInitialMemberCommand(operator(TENANT, **actor), group, email)


async def test_a_first_member_is_found_by_address_and_added_to_the_chosen_group() -> None:
    rig = _Rig()
    ids = await rig.provisioned(Role.LEAD)
    user = rig.directory.add_user(DIRECTORY_ID, JANE)
    with as_tenant(TENANT):
        change = await rig.first_member().execute(_first(Role.TENANT_ADMIN))

    assert change.group_id == ids[Role.TENANT_ADMIN] and change.changed
    assert rig.directory.members_of[(DIRECTORY_ID, ids[Role.TENANT_ADMIN])] == [user]


async def test_adding_the_same_person_again_is_not_an_error() -> None:
    rig = _Rig()
    await rig.provisioned()
    rig.directory.add_user(DIRECTORY_ID, JANE)
    with as_tenant(TENANT):
        await rig.first_member().execute(_first(Role.TENANT_ADMIN))
        again = await rig.first_member().execute(_first(Role.TENANT_ADMIN))
    assert not again.changed


async def test_a_person_who_is_not_in_the_directory_is_refused_and_nothing_is_added() -> None:
    rig = _Rig()
    await rig.provisioned()
    with as_tenant(TENANT), pytest.raises(ValidationFailed) as refused:
        await rig.first_member().execute(_first(Role.TENANT_ADMIN, "nobody@example-trust.test"))
    assert "nobody" not in refused.value.message
    assert not any(call == "add_member" for call, _ in rig.directory.calls)


async def test_a_group_that_has_not_been_made_cannot_take_members() -> None:
    rig = _Rig()
    rig.directory.add_user(DIRECTORY_ID, JANE)
    with as_tenant(TENANT), pytest.raises(NotAllowed):
        await rig.first_member().execute(_first(Role.LEAD))


async def test_a_group_that_exists_but_was_never_mapped_by_us_takes_no_first_member() -> None:
    directory = FakeEntraGroups()
    await directory.create_group(DIRECTORY_ID, "F81044_overwatch_lead", "by hand")
    directory.add_user(DIRECTORY_ID, JANE)
    rig = _Rig(directory=directory)
    with as_tenant(TENANT), pytest.raises(NotAllowed):
        await rig.first_member().execute(_first(Role.LEAD))


@pytest.mark.parametrize("role", [Role.PLATFORM_OPERATOR, Role.NETWORK_ADMIN, Role.SUPPORT])
async def test_there_is_no_first_member_for_a_role_with_no_group(role: Role) -> None:
    rig = _Rig()
    await rig.provisioned()
    with as_tenant(TENANT), pytest.raises(ValidationFailed):
        await rig.first_member().execute(_first(role))


async def test_only_the_platform_operator_adds_a_first_member() -> None:
    rig = _Rig()
    await rig.provisioned()
    rig.directory.add_user(DIRECTORY_ID, JANE)
    with as_tenant(TENANT), pytest.raises(NotAllowed):
        await rig.first_member().execute(_first(Role.TENANT_ADMIN, role=Role.TENANT_ADMIN))


async def test_the_first_members_audit_has_a_keyed_hash_and_never_the_address() -> None:
    rig = _Rig()
    ids = await rig.provisioned()
    user = rig.directory.add_user(DIRECTORY_ID, JANE)
    with as_tenant(TENANT):
        await rig.first_member().execute(_first(Role.TENANT_ADMIN))

    entry = rig.world.audit[-1]
    assert entry.use_case == "AddInitialGroupMember"
    assert entry.entity_ids == (ids[Role.TENANT_ADMIN],)
    assert entry.snapshot["emailHash"] == hash_email(JANE, SECRET)
    blob = json.dumps(entry.snapshot) + repr(entry.entity_ids) + repr(entry.actor)
    for leak in (JANE, JANE.lower(), "jane.member", "example-trust", user):
        assert leak not in blob


# ------------------------------------------------------------------ the tenant administrator


async def _managed(rig: _Rig, *roles: Role) -> dict[Role, str]:
    ids = await rig.provisioned(*roles)
    return ids


async def test_the_administrator_sees_the_groups_overwatch_made_and_who_is_in_them() -> None:
    rig = _Rig()
    ids = await _managed(rig, Role.LEAD)
    rig.directory.add_user(DIRECTORY_ID, JANE)
    with as_tenant(TENANT):
        await rig.first_member().execute(_first(Role.TENANT_ADMIN))
        view = await rig.reader().execute(rig.admin())

    assert view.set_up
    assert [(g.name, g.role, g.missing) for g in view.groups] == [
        ("F81044_overwatch_tenant-admin", Role.TENANT_ADMIN, False),
        ("F81044_overwatch_lead", Role.LEAD, False),
    ]
    admins = next(g for g in view.groups if g.role is Role.TENANT_ADMIN)
    assert [m.mail for m in admins.members] == [JANE.lower()]
    assert {g.group_id for g in view.groups} == set(ids.values())


async def test_a_group_the_organisation_mapped_by_hand_is_not_listed_or_changeable() -> None:
    rig = _Rig()
    await _managed(rig)
    rig.directory.groups[DIRECTORY_ID][STAFF_GROUP_ID] = "All clinical staff"
    rig.world.config.mapping_list.append(
        RoleMapping(STAFF_GROUP_ID, Role.CLINICAL, MappingStatus.ACTIVE)
    )
    with as_tenant(TENANT):
        view = await rig.reader().execute(rig.admin())
    assert STAFF_GROUP_ID not in {g.group_id for g in view.groups}


async def test_a_group_deleted_in_the_directory_is_shown_as_missing_not_as_a_failure() -> None:
    rig = _Rig()
    ids = await _managed(rig, Role.LEAD)
    rig.directory.delete_group(DIRECTORY_ID, ids[Role.LEAD])
    with as_tenant(TENANT):
        view = await rig.reader().execute(rig.admin())
    lead = next(g for g in view.groups if g.role is Role.LEAD)
    assert lead.missing and lead.name is None and lead.members == ()


async def test_before_consent_the_administrator_sees_that_nothing_is_set_up() -> None:
    rig = _Rig(consent=None)
    with as_tenant(TENANT):
        view = await rig.reader().execute(rig.admin())
    assert not view.set_up and view.groups == () and rig.directory.calls == []


@pytest.mark.parametrize(
    "role", [r for r in Role if r is not Role.TENANT_ADMIN], ids=lambda r: r.value
)
async def test_only_the_tenant_administrator_reads_or_changes_membership(role: Role) -> None:
    rig = _Rig()
    ids = await _managed(rig)
    who = operator(TENANT, "someone", role)
    with as_tenant(TENANT):
        with pytest.raises(NotAllowed):
            await rig.reader().execute(who)
        with pytest.raises(NotAllowed):
            await rig.changer().add(ChangeMemberCommand(who, ids[Role.TENANT_ADMIN], JANE))
        with pytest.raises(NotAllowed):
            await rig.changer().remove(
                ChangeMemberCommand(who, ids[Role.TENANT_ADMIN], user_id=SP_ID)
            )
    assert not any(call in ("add_member", "remove_member") for call, _ in rig.directory.calls)


async def test_the_administrator_adds_a_person_and_the_change_is_audited_without_the_address() -> (
    None
):
    rig = _Rig()
    ids = await _managed(rig, Role.LEAD)
    user = rig.directory.add_user(DIRECTORY_ID, SAM)
    with as_tenant(TENANT):
        change = await rig.changer().add(ChangeMemberCommand(rig.admin(), ids[Role.LEAD], SAM))

    assert change.changed
    assert rig.directory.members_of[(DIRECTORY_ID, ids[Role.LEAD])] == [user]
    entry = rig.world.audit[-1]
    assert entry.use_case == "AddEntraGroupMember"
    assert entry.actor.practitioner_id == "admin-ref-1" and entry.actor.role is Role.TENANT_ADMIN
    assert entry.entity_ids == (ids[Role.LEAD],)
    blob = json.dumps(entry.snapshot) + repr(entry.entity_ids)
    for leak in (SAM, "sam.second", "example-trust", user):
        assert leak not in blob
    assert rig.world.commits == 2  # the set-up's and this change's


async def test_nothing_about_a_member_is_stored_in_the_graph() -> None:
    rig = _Rig()
    ids = await _managed(rig, Role.LEAD)
    rig.directory.add_user(DIRECTORY_ID, SAM)
    before = list(rig.world.config.mapping_list)
    with as_tenant(TENANT):
        await rig.changer().add(ChangeMemberCommand(rig.admin(), ids[Role.LEAD], SAM))
    assert rig.world.config.mapping_list == before  # only the group-to-role mappings exist
    # `versions` is the configuration versions the platform defaults write (DEC-1322), not a member.
    assert {k for k in vars(rig.world.config) if k not in ("current", "versions")} == {
        "contact_list",
        "channel_list",
        "retention_list",
        "binding_list",
        "mapping_list",
    }


async def test_a_person_who_is_not_found_is_refused() -> None:
    rig = _Rig()
    ids = await _managed(rig)
    with as_tenant(TENANT), pytest.raises(ValidationFailed):
        await rig.changer().add(
            ChangeMemberCommand(rig.admin(), ids[Role.TENANT_ADMIN], "ghost@example-trust.test")
        )
    assert rig.world.audited() == ["ProvisionEntraGroups"]


async def test_an_outsider_is_invited_and_added_and_the_audit_has_no_address() -> None:
    rig = _Rig()
    ids = await _managed(rig, Role.LEAD)
    outsider = "clyde@softjump.example"
    with as_tenant(TENANT):
        result = await rig.changer().invite(
            ChangeMemberCommand(rig.admin(), ids[Role.LEAD], outsider)
        )

    assert result.invited and result.changed and result.directory_id == DIRECTORY_ID
    guest = rig.directory.users[DIRECTORY_ID][outsider]
    assert rig.directory.members_of[(DIRECTORY_ID, ids[Role.LEAD])] == [guest]
    entry = rig.world.audit[-1]
    assert entry.use_case == "InviteEntraGroupMember" and entry.snapshot["invited"] is True
    blob = json.dumps(entry.snapshot) + repr(entry.entity_ids)
    for leak in (outsider, "softjump", guest):
        assert leak not in blob


async def test_a_person_already_in_the_directory_is_added_without_a_new_invitation() -> None:
    rig = _Rig()
    ids = await _managed(rig, Role.LEAD)
    rig.directory.add_user(DIRECTORY_ID, SAM)
    with as_tenant(TENANT):
        result = await rig.changer().invite(ChangeMemberCommand(rig.admin(), ids[Role.LEAD], SAM))
    assert result.changed and not result.invited
    assert "invite_user" not in [call for call, _ in rig.directory.calls]


async def test_a_refused_invitation_adds_nobody_and_records_nothing() -> None:
    rig = _Rig()
    ids = await _managed(rig, Role.LEAD)
    rig.directory.invites_refused = True
    with as_tenant(TENANT), pytest.raises(InviteNotPermitted):
        await rig.changer().invite(
            ChangeMemberCommand(rig.admin(), ids[Role.LEAD], "clyde@softjump.example")
        )
    assert "add_member" not in [call for call, _ in rig.directory.calls]
    assert rig.world.audited() == ["ProvisionEntraGroups"]


@pytest.mark.parametrize(
    "role", [r for r in Role if r is not Role.TENANT_ADMIN], ids=lambda r: r.value
)
async def test_only_the_tenant_administrator_invites(role: Role) -> None:
    rig = _Rig()
    ids = await _managed(rig)
    who = operator(TENANT, "someone", role)
    with as_tenant(TENANT), pytest.raises(NotAllowed):
        await rig.changer().invite(
            ChangeMemberCommand(who, ids[Role.TENANT_ADMIN], "clyde@softjump.example")
        )
    assert "invite_user" not in [call for call, _ in rig.directory.calls]


async def test_an_invitation_to_a_group_outside_the_prefix_is_refused_before_any_invitation() -> (
    None
):
    rig = _Rig()
    await _managed(rig)
    rig.directory.groups[DIRECTORY_ID][STAFF_GROUP_ID] = "All clinical staff"
    with as_tenant(TENANT), pytest.raises(NotAllowed):
        await rig.changer().invite(
            ChangeMemberCommand(rig.admin(), STAFF_GROUP_ID, "clyde@softjump.example")
        )
    assert "invite_user" not in [call for call, _ in rig.directory.calls]


async def test_the_administrator_removes_a_person_and_it_is_audited() -> None:
    rig = _Rig()
    ids = await _managed(rig, Role.LEAD)
    user = rig.directory.add_user(DIRECTORY_ID, SAM)
    with as_tenant(TENANT):
        await rig.changer().add(ChangeMemberCommand(rig.admin(), ids[Role.LEAD], SAM))
        change = await rig.changer().remove(
            ChangeMemberCommand(rig.admin(), ids[Role.LEAD], user_id=user)
        )

    assert change.changed and rig.directory.members_of[(DIRECTORY_ID, ids[Role.LEAD])] == []
    entry = rig.world.audit[-1]
    assert entry.use_case == "RemoveEntraGroupMember" and entry.entity_ids == (ids[Role.LEAD],)
    assert user not in json.dumps(entry.snapshot) and SAM not in json.dumps(entry.snapshot)


async def test_removing_a_person_who_is_not_in_the_group_changes_nothing() -> None:
    rig = _Rig()
    ids = await _managed(rig, Role.LEAD)
    user = rig.directory.add_user(DIRECTORY_ID, SAM)
    with as_tenant(TENANT):
        change = await rig.changer().remove(
            ChangeMemberCommand(rig.admin(), ids[Role.LEAD], user_id=user)
        )
    assert not change.changed


async def test_a_removal_from_a_group_outside_the_prefix_is_refused() -> None:
    rig = _Rig()
    await _managed(rig)
    user = rig.directory.add_user(DIRECTORY_ID, SAM)
    rig.directory.groups[DIRECTORY_ID][STAFF_GROUP_ID] = "All clinical staff"
    rig.directory.members_of[(DIRECTORY_ID, STAFF_GROUP_ID)] = [user]
    rig.world.config.mapping_list.append(
        RoleMapping(STAFF_GROUP_ID, Role.CLINICAL, MappingStatus.ACTIVE)
    )
    with as_tenant(TENANT), pytest.raises(NotAllowed):
        await rig.changer().remove(ChangeMemberCommand(rig.admin(), STAFF_GROUP_ID, user_id=user))

    assert rig.directory.members_of[(DIRECTORY_ID, STAFF_GROUP_ID)] == [user]
    assert not any(call == "remove_member" for call, _ in rig.directory.calls)


async def test_an_add_to_a_group_outside_the_prefix_is_refused() -> None:
    rig = _Rig()
    await _managed(rig)
    rig.directory.add_user(DIRECTORY_ID, SAM)
    rig.directory.groups[DIRECTORY_ID][STAFF_GROUP_ID] = "Domain Admins"
    rig.world.config.mapping_list.append(
        RoleMapping(STAFF_GROUP_ID, Role.LEAD, MappingStatus.ACTIVE)
    )
    with as_tenant(TENANT), pytest.raises(NotAllowed):
        await rig.changer().add(ChangeMemberCommand(rig.admin(), STAFF_GROUP_ID, SAM))
    assert not any(call == "add_member" for call, _ in rig.directory.calls)


async def test_a_group_with_the_prefix_that_we_never_mapped_is_refused() -> None:
    rig = _Rig()
    await _managed(rig)
    rig.directory.add_user(DIRECTORY_ID, SAM)
    stray = await rig.directory.create_group(DIRECTORY_ID, "F81044_overwatch_lead", "made by hand")
    with as_tenant(TENANT), pytest.raises(NotAllowed):
        await rig.changer().add(ChangeMemberCommand(rig.admin(), stray, SAM))


async def test_a_mapped_group_whose_directory_name_says_another_role_is_refused() -> None:
    rig = _Rig()
    ids = await _managed(rig, Role.LEAD)
    rig.directory.groups[DIRECTORY_ID][ids[Role.LEAD]] = "F81044_overwatch_clinical"  # renamed
    rig.directory.add_user(DIRECTORY_ID, SAM)
    with as_tenant(TENANT), pytest.raises(NotAllowed):
        await rig.changer().add(ChangeMemberCommand(rig.admin(), ids[Role.LEAD], SAM))


@pytest.mark.parametrize("bad", ["", "not-a-guid", "x" * 40, "../groups", None, 7])
async def test_a_group_id_that_is_not_an_id_is_refused(bad: object) -> None:
    rig = _Rig()
    await _managed(rig)
    with as_tenant(TENANT), pytest.raises(NotAllowed):
        await rig.changer().add(ChangeMemberCommand(rig.admin(), bad, JANE))  # type: ignore[arg-type]


async def test_a_retired_mapping_is_not_a_group_the_administrator_may_change() -> None:
    rig = _Rig()
    ids = await _managed(rig, Role.LEAD)
    rig.world.config.mapping_list = [
        RoleMapping(m.group_object_id, m.role, MappingStatus.RETIRED) if m.role is Role.LEAD else m
        for m in rig.world.config.mapping_list
    ]
    rig.directory.add_user(DIRECTORY_ID, SAM)
    with as_tenant(TENANT), pytest.raises(NotAllowed):
        await rig.changer().add(ChangeMemberCommand(rig.admin(), ids[Role.LEAD], SAM))


async def test_the_last_administrator_cannot_be_removed() -> None:
    rig = _Rig()
    ids = await _managed(rig)
    user = rig.directory.add_user(DIRECTORY_ID, JANE)
    with as_tenant(TENANT):
        await rig.first_member().execute(_first(Role.TENANT_ADMIN))
        with pytest.raises(Conflict):
            await rig.changer().remove(
                ChangeMemberCommand(rig.admin(), ids[Role.TENANT_ADMIN], user_id=user)
            )
        second = rig.directory.add_user(DIRECTORY_ID, SAM)
        await rig.changer().add(ChangeMemberCommand(rig.admin(), ids[Role.TENANT_ADMIN], SAM))
        removed = await rig.changer().remove(
            ChangeMemberCommand(rig.admin(), ids[Role.TENANT_ADMIN], user_id=second)
        )
    assert removed.changed


async def test_a_group_deleted_in_the_directory_fails_clearly_and_leaves_the_mapping_alone() -> (
    None
):
    rig = _Rig()
    ids = await _managed(rig, Role.LEAD)
    rig.directory.delete_group(DIRECTORY_ID, ids[Role.LEAD])
    rig.directory.add_user(DIRECTORY_ID, SAM)
    mappings = list(rig.world.config.mapping_list)
    audits = list(rig.world.audit)
    with as_tenant(TENANT), pytest.raises(GroupMissing):
        await rig.changer().add(ChangeMemberCommand(rig.admin(), ids[Role.LEAD], SAM))

    assert rig.world.config.mapping_list == mappings and rig.world.audit == audits


async def test_when_the_directory_is_down_nothing_is_audited_as_done() -> None:
    rig = _Rig()
    ids = await _managed(rig, Role.LEAD)
    rig.directory.add_user(DIRECTORY_ID, SAM)
    rig.directory.unavailable = True
    audits = list(rig.world.audit)
    with as_tenant(TENANT), pytest.raises(GraphUnavailable):
        await rig.changer().add(ChangeMemberCommand(rig.admin(), ids[Role.LEAD], SAM))
    assert rig.world.audit == audits


async def test_another_tenants_administrator_cannot_change_this_tenants_group() -> None:
    directory = FakeEntraGroups()
    a = _Rig(directory=directory)
    ids = await _managed(a, Role.LEAD)
    directory.add_user(DIRECTORY_ID, SAM)
    b = _Rig(tenant_id=OTHER, ods="G99999", directory=directory)  # shares the directory fake
    with as_tenant(OTHER), pytest.raises(NotAllowed):
        await b.changer().add(
            ChangeMemberCommand(operator(OTHER, "b-admin", Role.TENANT_ADMIN), ids[Role.LEAD], SAM)
        )
    assert directory.members_of.get((DIRECTORY_ID, ids[Role.LEAD]), []) == []


# ------------------------------------------------------------------ the administrator: the lookup


async def test_the_administrator_finds_people_by_the_start_of_a_name_or_address() -> None:
    rig = _Rig()
    rig.directory.add_user(DIRECTORY_ID, JANE, "Jane Member")
    rig.directory.add_user(DIRECTORY_ID, SAM, "Sam Second")
    with as_tenant(TENANT):
        by_name = await rig.searcher().execute(rig.admin(), "jan")
        by_address = await rig.searcher().execute(rig.admin(), " sam.sec ")

    assert [(m.display_name, m.mail) for m in by_name] == [("Jane Member", JANE.lower())]
    assert [m.display_name for m in by_address] == ["Sam Second"]
    # The consent's directory is the one asked, and nothing the request says chooses another.
    assert [c for c in rig.directory.calls if c[0] == "search_users"] == [
        ("search_users", (DIRECTORY_ID,)),
        ("search_users", (DIRECTORY_ID,)),
    ]


async def test_a_search_from_anyone_but_the_administrator_is_refused_and_asks_nothing() -> None:
    rig = _Rig()
    rig.directory.add_user(DIRECTORY_ID, JANE, "Jane Member")
    with as_tenant(TENANT), pytest.raises(NotAllowed):
        await rig.searcher().execute(operator(TENANT, "lead-ref", Role.LEAD), "jan")
    assert rig.directory.calls == []


async def test_a_search_for_another_tenants_administrator_is_refused() -> None:
    rig = _Rig()
    with as_tenant(TENANT), pytest.raises(Exception) as refused:  # noqa: PT011
        await rig.searcher().execute(operator(OTHER, "admin-ref-1", Role.TENANT_ADMIN), "jan")
    assert type(refused.value).__name__ in {"TenantMismatch", "NotAllowed"}
    assert rig.directory.calls == []


@pytest.mark.parametrize("term", ["", "a", "x" * 65, "ja<n>"])
async def test_a_bad_term_is_refused_before_the_directory_is_asked(term: str) -> None:
    rig = _Rig()
    with as_tenant(TENANT), pytest.raises(ValidationFailed):
        await rig.searcher().execute(rig.admin(), term)
    assert rig.directory.calls == []


async def test_without_the_organisations_consent_there_is_nothing_to_search() -> None:
    rig = _Rig(consent=None)
    with as_tenant(TENANT), pytest.raises(NotAllowed):
        await rig.searcher().execute(rig.admin(), "jan")
    assert rig.directory.calls == []


async def test_a_directory_that_cannot_be_reached_is_the_graph_refusal_and_nothing_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = _Rig()
    rig.directory.unavailable = True
    with as_tenant(TENANT), pytest.raises(GraphUnavailable):
        await rig.searcher().execute(rig.admin(), "jane.secret")
    assert "jane.secret" not in caplog.text
