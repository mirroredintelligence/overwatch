"""The admin-consent invitation (DEC-1316): invite, read, confirm.

No Neo4j and no network: an in-memory invite store on a recording unit of work, the recording email
senders, and a fake Graph check. What is proved: the email goes from the tenant's own sender when it
has one and from the platform's when it has none; the link is the consent link with a state whose
hash alone is stored; the address is never stored or audited in the clear; a resend revokes the old
link; and the invite becomes consented only when Graph says the app is installed and holds the
group permission, never on the redirect's say-so.
"""

import json
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from overwatch.adapters.testing.fixed_ids import SequentialIds
from overwatch.adapters.testing.fixed_secrets import FixedSecretStore
from overwatch.adapters.testing.recording_senders import (
    FixedSenderResolver,
    RecordingEmailSender,
)
from overwatch.application.ports.outbound.admin_consent import AppInstallation, GraphUnavailable
from overwatch.application.ports.outbound.tokens import LINK_TOKEN_SECRET
from overwatch.application.use_cases.admin_consent import (
    NOT_ACCEPTED,
    REASON_DECLINED,
    REASON_NOT_INSTALLED,
    REASON_ROLE_MISSING,
    REASON_UNREACHABLE,
    AdminConsentLinks,
    ConfirmAdminConsent,
    InviteAdminConsent,
    InviteAdminConsentCommand,
    ReadAdminConsent,
)
from overwatch.domain.codes import Role
from overwatch.domain.errors import NotAllowed, NotFound, ValidationFailed
from overwatch.domain.model.tenant import TenantStatus
from overwatch.domain.model.tenant_records import BindingStatus, EntraBinding
from overwatch.domain.rules.admin_consent import (
    INVITE_VALID_FOR,
    REQUIRED_APP_ROLE,
    AdminConsentInvite,
    EffectiveStatus,
    InviteStatus,
    hash_state,
)
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
from tests.support.tenant_samples import make_tenant

CLIENT = "7fb43bde-6a6d-4aed-9cac-9118de48ab52"
RETURN = "https://overwatch.mirroredintelligence.com/admin-consent/return"
LINKS = AdminConsentLinks(CLIENT, RETURN)
ADDRESS = "Jane.Admin@Example-Trust.test"
SECRET = b"test-only-link-token-secret-0123456789"


class _Consents:
    """The invite store of one tenant, in memory, keyed by the tenant the unit was bound to."""

    def __init__(self) -> None:
        self.by_tenant: dict[str, list[AdminConsentInvite]] = {}
        self.scope: str = ""

    def _mine(self) -> list[AdminConsentInvite]:
        return self.by_tenant.setdefault(self.scope, [])

    async def add(self, invite: AdminConsentInvite) -> None:
        self._mine().append(invite)

    async def by_state_hash(self, state_hash: str) -> AdminConsentInvite | None:
        return next((i for i in self._mine() if i.state_hash == state_hash), None)

    async def latest(self) -> AdminConsentInvite | None:
        mine = sorted(self._mine(), key=lambda i: i.created_at, reverse=True)
        return mine[0] if mine else None

    async def revoke_open(self, at: datetime) -> int:
        count = 0
        for index, invite in enumerate(self._mine()):
            if invite.status is InviteStatus.PENDING:
                self._mine()[index] = replace(invite, status=InviteStatus.REVOKED, revoked_at=at)
                count += 1
        return count

    async def mark_consented(self, invite_id: str, at: datetime) -> bool:
        for index, invite in enumerate(self._mine()):
            if invite.invite_id == invite_id and invite.status is InviteStatus.PENDING:
                self._mine()[index] = replace(
                    invite, status=InviteStatus.CONSENTED, consented_at=at, last_reason=None
                )
                return True
        return False

    async def set_reason(self, invite_id: str, reason: str) -> None:
        for index, invite in enumerate(self._mine()):
            if invite.invite_id == invite_id:
                self._mine()[index] = replace(invite, last_reason=reason)


class _Clock(FixedNow):
    def set(self, value: datetime) -> None:
        self._value = value


class _Graph:
    def __init__(self, result: AppInstallation | Exception) -> None:
        self.result = result
        self.asked: list[str] = []

    async def check(self, directory_id: str) -> AppInstallation:
        self.asked.append(directory_id)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


INSTALLED = AppInstallation(True, frozenset({REQUIRED_APP_ROLE, "User.Read.All"}))


class _Rig:
    def __init__(self, *tenants: Any, graph: AppInstallation | Exception = INSTALLED) -> None:
        self.platform = FakePlatform(*tenants)
        self.world = FakeWorld()
        self.consents = _Consents()
        self.tenant_email = RecordingEmailSender("tenant-own")
        self.platform_email = RecordingEmailSender("platform")
        self.graph = _Graph(graph)
        self.now = _Clock()
        self.world.config.binding_list = [EntraBinding(DIRECTORY_ID, BindingStatus.PENDING)]

    def factory(self) -> Any:
        from overwatch.application.tenancy import current_scope_or_none

        def make() -> FakeUnit:
            scope = current_scope_or_none()
            unit = FakeUnit(self.world, scope)
            self.consents.scope = "" if scope is None else scope.value
            unit.admin_consents = self.consents  # type: ignore[attr-defined]
            return unit

        return make

    def senders(self, *, tenant_has_own: bool) -> FixedSenderResolver:
        return FixedSenderResolver(
            email={TENANT: self.tenant_email} if tenant_has_own else {},
            platform_email=self.platform_email,
        )

    def invite_case(self, *, tenant_has_own: bool = False) -> InviteAdminConsent:
        return InviteAdminConsent(
            self.platform,  # type: ignore[arg-type]
            self.factory(),
            self.now,
            SequentialIds(),
            FixedSecretStore({LINK_TOKEN_SECRET: SECRET}),
            self.senders(tenant_has_own=tenant_has_own),
            LINKS,
        )

    def read_case(self) -> ReadAdminConsent:
        return ReadAdminConsent(self.factory(), self.now)

    def confirm_case(self) -> ConfirmAdminConsent:
        return ConfirmAdminConsent(
            self.platform,  # type: ignore[arg-type]
            self.factory(),
            self.now,
            self.graph,
        )


def _command(email: str = ADDRESS, **actor: Any) -> InviteAdminConsentCommand:
    return InviteAdminConsentCommand(operator(**actor), email)


def _rig(**kwargs: Any) -> _Rig:
    return _Rig(provisioning_tenant(ods_code="F81044"), **kwargs)


def _state_sent(email: RecordingEmailSender) -> str:
    [sent] = email.sent
    link = next(line for line in sent.text.splitlines() if line.startswith("https://"))
    return parse_qs(urlparse(link).query)["state"][0]


# ------------------------------------------------------------------ the invitation


async def test_with_no_sender_of_its_own_the_email_goes_from_the_platform() -> None:
    rig = _rig()
    with as_tenant(TENANT):
        await rig.invite_case(tenant_has_own=False).execute(_command())

    assert rig.tenant_email.sent == []
    [sent] = rig.platform_email.sent
    assert sent.to == ADDRESS.lower()
    assert sent.html is None and sent.tenant == TENANT


async def test_a_tenant_with_its_own_sender_sends_from_it_not_the_platform() -> None:
    rig = _rig()
    with as_tenant(TENANT):
        await rig.invite_case(tenant_has_own=True).execute(_command())

    assert rig.platform_email.sent == []
    [sent] = rig.tenant_email.sent
    assert sent.to == ADDRESS.lower()


async def test_the_email_names_the_organisation_and_carries_the_consent_link_with_the_state() -> (
    None
):
    rig = _rig()
    with as_tenant(TENANT):
        view = await rig.invite_case().execute(_command())

    [sent] = rig.platform_email.sent
    assert "New Organisation" in sent.subject and "F81044_overwatch_" in sent.text
    link = next(line for line in sent.text.splitlines() if line.startswith("https://"))
    url = urlparse(link)
    assert url.netloc == "login.microsoftonline.com"
    assert url.path == f"/{DIRECTORY_ID}/adminconsent"
    query = parse_qs(url.query)
    assert query["client_id"] == [CLIENT] and query["redirect_uri"] == [RETURN]
    assert query["state"][0].startswith(f"{TENANT}.")
    assert view.status is EffectiveStatus.PENDING
    assert view.expires_at == NOW + INVITE_VALID_FOR == NOW + timedelta(days=7)
    assert view.email_masked == "j***@example-trust.test"


async def test_only_hashes_are_stored_and_the_address_and_state_are_nowhere_at_rest() -> None:
    rig = _rig()
    with as_tenant(TENANT):
        await rig.invite_case().execute(_command())

    state = _state_sent(rig.platform_email)
    [stored] = rig.consents.by_tenant[TENANT]
    assert stored.state_hash == hash_state(state) and stored.status is InviteStatus.PENDING
    blob = (
        repr(stored)
        + json.dumps([e.snapshot for e in rig.world.audit])
        + repr([e.entity_ids for e in rig.world.audit])
    )
    for secret in (state, state.partition(".")[2], ADDRESS, ADDRESS.lower(), "jane.admin"):
        assert secret not in blob
    assert rig.world.audited() == ["InviteAdminConsent"] and rig.world.commits == 1


async def test_a_resend_revokes_the_old_link_and_only_the_newest_can_count() -> None:
    rig = _rig()
    with as_tenant(TENANT):
        await rig.invite_case().execute(_command())
        old_state = _state_sent(rig.platform_email)
        rig.platform_email.sent.clear()
        await rig.invite_case().execute(_command())
        new_state = _state_sent(rig.platform_email)

        old_result = await rig.confirm_case().execute(old_state, admin_consent=True)
        new_result = await rig.confirm_case().execute(new_state, admin_consent=True)

    statuses = sorted(i.status.value for i in rig.consents.by_tenant[TENANT])
    assert statuses == ["consented", "revoked"]
    assert old_result.status is EffectiveStatus.REVOKED
    assert new_result.status is EffectiveStatus.CONSENTED


async def test_a_directory_must_be_bound_first() -> None:
    rig = _rig()
    rig.world.config.binding_list = []
    with as_tenant(TENANT), pytest.raises(NotAllowed):
        await rig.invite_case().execute(_command())
    assert rig.platform_email.sent == [] and rig.consents.by_tenant == {}


async def test_a_revoked_directory_binding_is_not_used() -> None:
    rig = _rig()
    rig.world.config.binding_list = [EntraBinding(DIRECTORY_ID, BindingStatus.REVOKED)]
    with as_tenant(TENANT), pytest.raises(NotAllowed):
        await rig.invite_case().execute(_command())


async def test_a_send_the_provider_refuses_records_nothing() -> None:
    rig = _rig()
    rig.platform_email.fail_next()
    with as_tenant(TENANT), pytest.raises(NotAllowed, match=NOT_ACCEPTED):
        await rig.invite_case().execute(_command())
    # The write is in the unit of work that is never committed, so the store rolls it back.
    assert rig.world.commits == 0 and rig.world.audit == []


async def test_with_no_sender_at_all_it_is_refused_before_anything_is_written() -> None:
    rig = _rig()
    use_case = InviteAdminConsent(
        rig.platform,  # type: ignore[arg-type]
        rig.factory(),
        rig.now,
        SequentialIds(),
        FixedSecretStore({LINK_TOKEN_SECRET: SECRET}),
        FixedSenderResolver(),
        LINKS,
    )
    with as_tenant(TENANT), pytest.raises(NotAllowed):
        await use_case.execute(_command())
    assert rig.consents.by_tenant.get(TENANT, []) == []


async def test_a_value_that_is_not_an_address_is_refused_first() -> None:
    rig = _rig()
    with as_tenant(TENANT), pytest.raises(ValidationFailed):
        await rig.invite_case().execute(_command("not an address"))
    assert rig.world.opened == 0


@pytest.mark.parametrize(
    "role", [r for r in Role if r is not Role.PLATFORM_OPERATOR], ids=lambda r: r.value
)
async def test_only_the_platform_operator_invites_and_reads(role: Role) -> None:
    rig = _rig()
    with as_tenant(TENANT):
        with pytest.raises(NotAllowed):
            await rig.invite_case().execute(_command(role=role))
        with pytest.raises(NotAllowed):
            await rig.read_case().execute(operator(role=role))
    assert rig.platform_email.sent == []


@pytest.mark.parametrize("status", [TenantStatus.SUSPENDED, TenantStatus.OFFBOARDED])
async def test_a_tenant_that_is_not_open_is_not_invited(status: TenantStatus) -> None:
    rig = _Rig(make_tenant(status, id=TENANT))
    with as_tenant(TENANT), pytest.raises(NotAllowed):
        await rig.invite_case().execute(_command())


# ------------------------------------------------------------------ the page's view


async def test_the_operator_sees_the_masked_address_and_the_effective_status() -> None:
    rig = _rig()
    with as_tenant(TENANT):
        assert await rig.read_case().execute(operator()) is None
        await rig.invite_case().execute(_command())
        pending = await rig.read_case().execute(operator())
        rig.now.set(NOW + INVITE_VALID_FOR)
        expired = await rig.read_case().execute(operator())

    assert pending is not None and pending.status is EffectiveStatus.PENDING
    assert pending.email_masked == "j***@example-trust.test"
    assert expired is not None and expired.status is EffectiveStatus.EXPIRED


# ------------------------------------------------------------------ the confirmation


async def _invited(rig: _Rig) -> str:
    with as_tenant(TENANT):
        await rig.invite_case().execute(_command())
    return _state_sent(rig.platform_email)


async def test_an_installed_app_with_the_group_permission_marks_it_consented() -> None:
    rig = _rig()
    state = await _invited(rig)
    with as_tenant(TENANT):
        result = await rig.confirm_case().execute(state, admin_consent=True)

    assert result.status is EffectiveStatus.CONSENTED and result.reason is None
    assert result.organisation == "New Organisation"
    assert rig.graph.asked == [DIRECTORY_ID]  # Graph was asked, in the invite's own directory
    [stored] = rig.consents.by_tenant[TENANT]
    assert stored.status is InviteStatus.CONSENTED and stored.consented_at == NOW
    assert rig.world.audited()[-1] == "ConfirmAdminConsent"


async def test_the_redirect_saying_yes_is_not_proof_when_the_app_is_not_installed() -> None:
    rig = _rig(graph=AppInstallation(False, reason="no service principal"))
    state = await _invited(rig)
    with as_tenant(TENANT):
        result = await rig.confirm_case().execute(state, admin_consent=True)

    assert result.status is EffectiveStatus.PENDING and result.reason == REASON_NOT_INSTALLED
    [stored] = rig.consents.by_tenant[TENANT]
    assert stored.status is InviteStatus.PENDING and stored.last_reason == REASON_NOT_INSTALLED


async def test_a_redirect_that_says_no_is_told_in_words_and_stays_pending() -> None:
    rig = _rig(graph=AppInstallation(False))
    state = await _invited(rig)
    with as_tenant(TENANT):
        result = await rig.confirm_case().execute(state, admin_consent=False)
    assert result.status is EffectiveStatus.PENDING and result.reason == REASON_DECLINED


async def test_an_installed_app_without_the_group_permission_stays_pending() -> None:
    rig = _rig(graph=AppInstallation(True, frozenset({"User.Read.All"})))
    state = await _invited(rig)
    with as_tenant(TENANT):
        result = await rig.confirm_case().execute(state, admin_consent=True)
    assert result.status is EffectiveStatus.PENDING and result.reason == REASON_ROLE_MISSING
    assert rig.consents.by_tenant[TENANT][0].status is InviteStatus.PENDING


async def test_when_graph_cannot_be_reached_nothing_changes() -> None:
    rig = _rig(graph=GraphUnavailable("down"))
    state = await _invited(rig)
    commits = rig.world.commits
    with as_tenant(TENANT):
        result = await rig.confirm_case().execute(state, admin_consent=True)
    assert result.status is EffectiveStatus.PENDING and result.reason == REASON_UNREACHABLE
    assert rig.world.commits == commits
    assert rig.consents.by_tenant[TENANT][0].last_reason is None


async def test_an_expired_invite_is_not_confirmed_and_graph_is_not_asked() -> None:
    rig = _rig()
    state = await _invited(rig)
    rig.now.set(NOW + INVITE_VALID_FOR + timedelta(seconds=1))
    with as_tenant(TENANT):
        result = await rig.confirm_case().execute(state, admin_consent=True)
    assert result.status is EffectiveStatus.EXPIRED
    assert rig.graph.asked == []


async def test_a_second_return_is_the_same_answer() -> None:
    rig = _rig()
    state = await _invited(rig)
    with as_tenant(TENANT):
        await rig.confirm_case().execute(state, admin_consent=True)
        again = await rig.confirm_case().execute(state, admin_consent=True)
    assert again.status is EffectiveStatus.CONSENTED
    assert len(rig.graph.asked) == 1


async def test_a_state_that_names_another_tenant_finds_nothing() -> None:
    rig = _Rig(provisioning_tenant(), provisioning_tenant(OTHER))
    state = await _invited(rig)  # an invite of TENANT
    with as_tenant(OTHER), pytest.raises(NotFound):
        await rig.confirm_case().execute(state, admin_consent=True)  # looked up in OTHER only
    assert rig.graph.asked == []
    assert rig.consents.by_tenant.get(OTHER, []) == []


async def test_a_made_up_state_finds_nothing_and_asks_graph_nothing() -> None:
    rig = _rig()
    await _invited(rig)
    with as_tenant(TENANT), pytest.raises(NotFound):
        await rig.confirm_case().execute(f"{TENANT}.{'A' * 43}", admin_consent=True)
    assert rig.graph.asked == []


async def test_a_tenant_that_has_left_is_not_confirmed() -> None:
    rig = _rig()
    state = await _invited(rig)
    rig.platform.tenants[TENANT] = make_tenant(TenantStatus.OFFBOARDED, id=TENANT)
    with as_tenant(TENANT), pytest.raises(NotFound):
        await rig.confirm_case().execute(state, admin_consent=True)
