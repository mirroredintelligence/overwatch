"""Inviting a tenant's first administrator (TEN-028, DEC-503, audit F section 2.5).

No Neo4j: a recording unit of work. What is proved here is what the invitation is made of and what
it must never hold: a link token tied to the tenant-keyed hash of the mobile, the number only in the
protected contact store, a sealed text from the tenant's own number, a link on the tenant's own
host, and an audit entry that names no number. The flow on a real graph is
`tests/integration/application/test_tenant_provisioning.py`.
"""

import json
from datetime import timedelta
from typing import Any

import pytest

from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.provisioning import TENANT_ADMIN_INVITE
from diucs.application.tenancy import ScopeId, TenantMismatch, TenantNotBound
from diucs.application.use_cases.tenant_access import (
    InviteTenantAdmin,
    InviteTenantAdminCommand,
    invitation_key,
)
from diucs.domain.codes import Role
from diucs.domain.errors import Conflict, NotAllowed, NotFound, ValidationFailed
from diucs.domain.model.tenant import TenantStatus
from diucs.domain.rules.registration import INVITATION_VALID_FOR
from tests.support.provisioning_fakes import (
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

MOBILE = "07700 900123"
HASH = "ab" * 32
TOKEN = "tokentokentokentokentoken"


class _Hasher:
    def __init__(self) -> None:
        self.hashed: list[str] = []

    def hash(self, number: str) -> str:
        self.hashed.append(number)
        return HASH


class _Tokens:
    def __init__(self) -> None:
        self.issued: list[tuple[str, str, str, object]] = []

    async def issue(self, purpose: str, about: str, phone_hash: str, expires: object) -> str:
        self.issued.append((purpose, about, phone_hash, expires))
        return TOKEN


class _Sealer:
    def seal(self, content: str, *, message_id: str, tenant_id: str, recipient_role_id: str) -> str:
        self.last = (content, message_id, tenant_id, recipient_role_id)
        return "sealed:" + message_id

    def unseal(self, *args: Any, **kwargs: Any) -> str:  # pragma: no cover - not used here
        raise AssertionError


class _Host:
    def __init__(self, url: str | None = "https://new-org.example.org") -> None:
        self.url = url

    async def host_url(self, scope: ScopeId) -> str:
        if self.url is None:
            from diucs.application.ports.outbound.tenants import TenantRecordInvalid

            raise TenantRecordInvalid("no host")
        return self.url


class _Rig:
    def __init__(self, *tenants: Any) -> None:
        self.platform = FakePlatform(*tenants)
        self.world = FakeWorld()
        self.hasher = _Hasher()
        self.tokens = _Tokens()
        self.sealer = _Sealer()
        self.host = _Host()
        self.contacts: dict[str, str] = {}
        self.communications: list[Any] = []
        self.outbox: list[Any] = []

    def factory(self) -> Any:
        def make() -> FakeUnit:
            unit = FakeUnit(self.world, self._scope())
            unit.contacts = _Namespace(put_phone=self._put_phone)  # type: ignore[attr-defined]
            unit.communications = _Namespace(add=self._add_communication)  # type: ignore[attr-defined]
            unit.outbox = _Namespace(add=self._add_outbox)  # type: ignore[attr-defined]
            return unit

        return make

    @staticmethod
    def _scope() -> ScopeId | None:
        from diucs.application.tenancy import current_scope_or_none

        return current_scope_or_none()

    async def _put_phone(self, key: str, number: str) -> None:
        self.contacts[key] = number

    async def _add_communication(self, communication: Any) -> None:
        self.communications.append(communication)

    async def _add_outbox(self, message: Any) -> None:
        self.outbox.append(message)

    def use_case(self) -> InviteTenantAdmin:
        return InviteTenantAdmin(
            self.platform,  # type: ignore[arg-type]
            self.factory(),
            lambda repo: self.tokens,  # type: ignore[arg-type, return-value]
            self.hasher,
            self.sealer,  # type: ignore[arg-type]
            FixedNow(),
            SequentialIds(),
            self.host,
        )


class _Namespace:
    def __init__(self, **attributes: Any) -> None:
        self.__dict__.update(attributes)


def _command(mobile: str = MOBILE, **actor: Any) -> InviteTenantAdminCommand:
    return InviteTenantAdminCommand(operator(**actor), mobile)


def _ready(rig: _Rig) -> _Rig:
    rig.world.config.make_ready()
    return rig


async def test_the_invitation_is_a_token_a_stored_number_a_sealed_text_and_an_audit_entry() -> None:
    rig = _ready(_Rig(provisioning_tenant()))

    with as_tenant(TENANT):
        result = await rig.use_case().execute(_command())

    assert result.expires_at == NOW + INVITATION_VALID_FOR == NOW + timedelta(hours=48)
    # The token: the tenant's own purpose, about the tenant's one invitation, the keyed hash.
    assert rig.tokens.issued == [
        (TENANT_ADMIN_INVITE, f"tenant-admin-{TENANT}", HASH, result.expires_at)
    ]
    assert TENANT_ADMIN_INVITE != "invite"  # never found by the reporters' text-code flow
    # The number, only in the protected contact store, in its stored (international) form.
    assert rig.contacts == {f"tenant-admin-{TENANT}": "+447700900123"}
    assert rig.hasher.hashed == ["07700900123"]
    assert rig.world.audited() == ["InviteTenantAdmin"] and rig.world.commits == 1


async def test_the_text_is_i2_with_the_tenants_system_name_and_a_link_on_its_own_host() -> None:
    rig = _ready(_Rig(provisioning_tenant()))
    with as_tenant(TENANT):
        await rig.use_case().execute(_command())

    [message] = rig.outbox
    sealed_text = json.loads(rig.sealer.last[0])["text"]
    assert f"https://new-org.example.org/i/{TOKEN}" in sealed_text
    assert "Sample capacity view" in sealed_text  # the tenant's wording, not a place name
    assert rig.sealer.last[2] == TENANT  # sealed for this tenant
    assert rig.sealer.last[3] == f"tenant-admin-{TENANT}"
    assert message.payload["recipient_role_id"] == f"tenant-admin-{TENANT}"
    assert message.payload["sealed_content"].startswith("sealed:")
    assert "text" not in message.payload  # the content is sealed, never in the clear


async def test_nothing_at_rest_holds_the_token_the_link_or_the_number() -> None:
    rig = _ready(_Rig(provisioning_tenant()))
    with as_tenant(TENANT):
        await rig.use_case().execute(_command())

    [communication] = rig.communications
    assert TOKEN not in communication.payload_text
    assert "[link]" in communication.payload_text
    assert communication.about_id is None  # a Communication is about a service, never a record
    audit = rig.world.audit[0]
    blob = json.dumps(audit.snapshot) + repr(audit.entity_ids)
    for secret in (TOKEN, "07700", "900123", "+44", HASH):
        assert secret not in blob
    for secret in (TOKEN, "07700", "900123"):
        assert secret not in repr(rig.outbox[0].payload)


@pytest.mark.parametrize(
    "role", [r for r in Role if r is not Role.PLATFORM_OPERATOR], ids=lambda r: r.value
)
async def test_only_the_platform_operator_invites(role: Role) -> None:
    rig = _ready(_Rig(provisioning_tenant()))
    with as_tenant(TENANT), pytest.raises(NotAllowed):
        await rig.use_case().execute(_command(role=role))
    assert rig.hasher.hashed == [] and rig.world.opened == 0 and rig.outbox == []


async def test_an_unnamed_operator_and_an_operator_of_another_tenant_are_refused_first() -> None:
    rig = _ready(_Rig(provisioning_tenant()))
    with as_tenant(TENANT):
        with pytest.raises(NotAllowed):
            await rig.use_case().execute(_command(ref=None))
        with pytest.raises(TenantMismatch):
            await rig.use_case().execute(_command(tenant=OTHER))
    assert rig.hasher.hashed == [] and rig.world.opened == 0


@pytest.mark.parametrize("mobile", ["", "01234 567890", "07700 90012", "hello", "+1 202 555 0100"])
async def test_a_mobile_that_is_not_a_uk_mobile_is_refused_before_anything_is_hashed(
    mobile: str,
) -> None:
    rig = _ready(_Rig(provisioning_tenant()))
    with as_tenant(TENANT), pytest.raises(ValidationFailed) as refused:
        await rig.use_case().execute(_command(mobile))
    # The refusal is the screen's fixed wording: it does not echo what was typed.
    assert str(refused.value) == "mobile: Enter a UK mobile number, like 07700 900123"
    assert rig.hasher.hashed == [] and rig.world.opened == 0


async def test_with_no_tenant_bound_nothing_is_done() -> None:
    rig = _ready(_Rig(provisioning_tenant()))
    with pytest.raises(TenantNotBound):
        await rig.use_case().execute(_command())


async def test_a_tenant_nobody_created_and_a_tenant_that_has_left_are_refused() -> None:
    with as_tenant(TENANT), pytest.raises(NotFound):
        await _ready(_Rig()).use_case().execute(_command())
    gone = provisioning_tenant(
        status=TenantStatus.OFFBOARDING, activated_at=NOW, offboarding_started_at=NOW
    )
    with as_tenant(TENANT), pytest.raises(NotAllowed):
        await _ready(_Rig(gone)).use_case().execute(_command())


async def test_a_second_invitation_is_a_conflict_while_the_first_is_open() -> None:
    rig = _ready(_Rig(provisioning_tenant()))
    rig.world.tokens.open_about[(TENANT_ADMIN_INVITE, invitation_key(ScopeId.tenant(TENANT)))] = (
        object()
    )
    with as_tenant(TENANT), pytest.raises(Conflict):
        await rig.use_case().execute(_command())
    assert rig.tokens.issued == [] and rig.outbox == [] and rig.contacts == {}


async def test_a_tenant_with_no_wording_is_not_invited_and_nothing_is_written() -> None:
    rig = _Rig(provisioning_tenant())  # no configuration in force: no system name
    with as_tenant(TENANT), pytest.raises(NotAllowed, match="system name"):
        await rig.use_case().execute(_command())
    assert rig.tokens.issued == [] and rig.contacts == {} and rig.outbox == []
    assert rig.world.commits == 0


async def test_a_tenant_with_no_host_cannot_be_sent_a_link_and_nothing_is_written() -> None:
    from diucs.application.ports.outbound.tenants import TenantRecordInvalid

    rig = _ready(_Rig(provisioning_tenant()))
    rig.host = _Host(None)
    with as_tenant(TENANT), pytest.raises(TenantRecordInvalid):
        await rig.use_case().execute(_command())
    assert rig.tokens.issued == [] and rig.world.opened == 0


def test_the_invitation_key_names_the_tenant_and_no_person() -> None:
    assert invitation_key(ScopeId.tenant(TENANT)) == f"tenant-admin-{TENANT}"
