"""The token exchange: the back end verifies the sign-in itself and issues the tenant-bound token
(TEN-043, DEC-522 to DEC-527, DEC-134 item 2, DEC-136 item 6, audit F A01 to A03).

The BFF holds no signing secret. It hands the back end the credential the person signed in with; the
back end has it verified (a fake verifier here), checks the tenant the HOST names against the
directory the person signed in through (the tenant's own VERIFIED binding), takes the role from the
tenant's role mapping, and signs. Every way of not getting a token is one `ExchangeRefused` with one
fixed message, so an answer says nothing about which directories, groups or tenants exist.

Stand-ins for the unit of work and the resolver record what they were asked; nothing reaches a
store.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Any, Self

import pytest

from diucs.adapters.testing.fake_identity_verifier import FakeIdentityVerifier
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.identity_verifier import Audience, VerifiedIdentity
from diucs.application.tenancy import ScopeId, TenantMismatch, bind_tenant, current_scope_or_none
from diucs.application.tenant_resolution import EntryRefused
from diucs.application.use_cases.exchange_token import (
    ACCOUNT_REF_SECRET,
    EXCHANGE_REFUSED_MESSAGE,
    SIGNING_SECRET,
    ExchangeDeviceCommand,
    ExchangeDeviceToken,
    ExchangeOperatorCommand,
    ExchangeOperatorToken,
    ExchangeRefused,
    ExchangeStaffCommand,
    ExchangeStaffToken,
    IssuedToken,
)
from diucs.domain.codes import Role
from diucs.domain.errors import DomainError
from diucs.domain.model.device import BoardScope, Device, DeviceStatus, DeviceType
from diucs.domain.model.tenant import SuspendMode, Tenant, TenantStatus
from diucs.domain.model.tenant_records import (
    BindingStatus,
    EntraBinding,
    MappingStatus,
    RoleMapping,
)
from diucs.domain.rules.bff_token import (
    OPERATOR_AUDIENCE,
    STAFF_AUDIENCE,
    TokenRejected,
    decode_bff_token,
    decode_operator_token,
)
from diucs.domain.rules.token_exchange import account_ref, staff_subject
from tests.support.tenant_samples import make_tenant

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
SIGNING = b"synthetic-bff-signing-secret-for-the-exchange-tests-01"
ACCOUNT_KEY = b"synthetic-account-ref-key-for-the-exchange-tests-02"
D_A = "11111111-1111-4111-8111-111111111111"
D_B = "22222222-2222-4222-8222-222222222222"
D_OPERATOR = "99999999-9999-4999-8999-999999999999"
OID = "33333333-3333-4333-8333-333333333333"
G_LEAD = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
G_ADVISOR = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
G_OTHER = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
CREDENTIAL = "synthetic-entra-id-token-0001"
DEVICE_TOKEN = "AbCdEfGhIjKlMnOpQrStUvW"

TENANT_A = make_tenant(TenantStatus.ACTIVE, id="tenant-a", epoch=4)
TENANT_B = make_tenant(TenantStatus.ACTIVE, id="tenant-b", epoch=2)


def secrets() -> FixedSecretStore:
    return FixedSecretStore({SIGNING_SECRET: SIGNING, ACCOUNT_REF_SECRET: ACCOUNT_KEY})


def identity(
    directory: str = D_A,
    groups: tuple[str, ...] = (G_LEAD,),
    app_roles: tuple[str, ...] = (),
    oid: str = OID,
) -> VerifiedIdentity:
    return VerifiedIdentity(
        directory_id=directory,
        object_id=oid,
        group_ids=frozenset(groups),
        app_roles=frozenset(app_roles),
    )


def verified(directory: str) -> EntraBinding:
    return EntraBinding(
        directory_id=directory,
        status=BindingStatus.VERIFIED,
        verified_at=NOW,
        verified_by_ref="operator-ref-1",
    )


def mapping(group: str, role: Role, status: MappingStatus = MappingStatus.ACTIVE) -> RoleMapping:
    return RoleMapping(group_object_id=group, role=role, status=status)


# ----------------------------------------------------------------------- stand-ins


class _Config:
    def __init__(self, bindings: list[EntraBinding], mappings: list[RoleMapping]) -> None:
        self._bindings = bindings
        self._mappings = mappings

    async def bindings(self) -> tuple[EntraBinding, ...]:
        return tuple(self._bindings)

    async def role_mappings(self) -> tuple[RoleMapping, ...]:
        return tuple(self._mappings)


class _Audit:
    def __init__(self, fail: bool = False) -> None:
        self.entries: list[AuditEntry] = []
        self._fail = fail

    async def append(self, entry: AuditEntry) -> None:
        if self._fail:
            raise ConnectionError("audit store down")
        self.entries.append(entry)


class _Uow:
    def __init__(self, config: _Config, audit: _Audit, scope: ScopeId | None) -> None:
        self.tenant_config = config
        self.audit = audit
        self._scope = scope
        self.commits = 0

    @property
    def unit_scope(self) -> ScopeId | None:
        return self._scope

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1


@dataclass
class _World:
    """Each tenant's configuration, read by the unit of work that opens under its scope."""

    configs: dict[str, _Config] = field(default_factory=dict)
    audit: _Audit = field(default_factory=_Audit)
    units: list[_Uow] = field(default_factory=list)

    def factory(self) -> _Uow:
        scope = current_scope_or_none()
        config = self.configs[scope.value] if scope is not None else _Config([], [])
        uow = _Uow(config, self.audit, scope)
        self.units.append(uow)
        return uow


def world(
    bindings: list[EntraBinding] | None = None,
    mappings: list[RoleMapping] | None = None,
    *,
    other: tuple[list[EntraBinding], list[RoleMapping]] | None = None,
) -> _World:
    built = _World()
    built.configs["tenant-a"] = _Config(
        [verified(D_A)] if bindings is None else bindings,
        [mapping(G_LEAD, Role.LEAD)] if mappings is None else mappings,
    )
    built.configs["tenant-b"] = _Config(*(other or ([verified(D_B)], [mapping(G_LEAD, Role.LEAD)])))
    return built


class _Ownership:
    """Which tenants own an active network, and which tenants it was asked about."""

    def __init__(self, *owners: str, fail: bool = False) -> None:
        self._owners = frozenset(owners)
        self._fail = fail
        self.asked: list[str] = []

    async def owns_active_network(self, tenant_id: str) -> bool:
        self.asked.append(tenant_id)
        if self._fail:
            raise ConnectionError("registry down")
        return tenant_id in self._owners


def staff_use_case(
    built: _World,
    verifier: FakeIdentityVerifier,
    store: FixedSecretStore | None = None,
    clock: FixedClock | None = None,
    ownership: _Ownership | None = None,
) -> ExchangeStaffToken:
    return ExchangeStaffToken(
        built.factory,  # type: ignore[arg-type]
        clock or FixedClock(NOW),
        verifier,
        store or secrets(),
        ownership,
    )


def accepting(
    who: VerifiedIdentity | None = None, audience: Audience = Audience.STAFF
) -> FakeIdentityVerifier:
    verifier = FakeIdentityVerifier()
    verifier.accepts(CREDENTIAL, who or identity(), audience)
    return verifier


async def exchange(
    use_case: ExchangeStaffToken, tenant: Tenant = TENANT_A, credential: str = CREDENTIAL
) -> IssuedToken:
    with bind_tenant(tenant.id):
        return await use_case.execute(ExchangeStaffCommand(tenant=tenant, credential=credential))


# ----------------------------------------------------------------------- staff: the token


async def test_a_member_gets_a_token_for_the_tenant_of_the_host_with_the_mapped_role() -> None:
    issued = await exchange(staff_use_case(world(), accepting()))

    claims = decode_bff_token(issued.token, SIGNING, NOW)
    assert claims.tenant == "tenant-a"
    assert claims.epoch == 4
    assert claims.role is Role.LEAD
    assert claims.services == frozenset()
    assert claims.device is None
    assert claims.expires_at == NOW + timedelta(hours=8)
    assert claims.sub == staff_subject(ACCOUNT_KEY, "tenant-a", D_A, OID)
    assert (issued.role, issued.expires_at) == (Role.LEAD, NOW + timedelta(hours=8))


async def test_the_token_is_for_the_api_audience() -> None:
    issued = await exchange(staff_use_case(world(), accepting()))

    import base64
    import json

    part = issued.token.split(".")[1]
    body = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    assert body["aud"] == STAFF_AUDIENCE
    with pytest.raises(TokenRejected):
        decode_operator_token(issued.token, SIGNING, NOW)


async def test_the_verifier_is_asked_for_the_staff_audience_and_nothing_else() -> None:
    verifier = accepting()

    await exchange(staff_use_case(world(), verifier))

    assert verifier.audiences_asked == (Audience.STAFF,)


async def test_the_highest_mapped_role_wins() -> None:
    built = world(mappings=[mapping(G_ADVISOR, Role.ADVISOR), mapping(G_LEAD, Role.LEAD)])
    verifier = accepting(identity(groups=(G_ADVISOR, G_LEAD)))

    issued = await exchange(staff_use_case(built, verifier))

    assert issued.role is Role.LEAD


async def test_a_read_only_suspended_tenants_administrator_gets_a_token_with_its_epoch() -> None:
    suspended = make_tenant(
        TenantStatus.SUSPENDED, id="tenant-a", epoch=5, suspend_mode=SuspendMode.READ_ONLY
    )
    forced = mapping(G_LEAD, Role.LEAD)
    object.__setattr__(forced, "role", Role.TENANT_ADMIN)  # the record refuses it; see the rules
    built = world(mappings=[forced])

    issued = await exchange(staff_use_case(built, accepting()), suspended)

    claims = decode_bff_token(issued.token, SIGNING, NOW)
    assert (claims.role, claims.epoch) == (Role.TENANT_ADMIN, 5)


async def test_the_token_is_new_each_time_it_is_asked_for_at_a_new_instant() -> None:
    clock = FixedClock(NOW)
    use_case = staff_use_case(world(), accepting(), clock=clock)

    first = await exchange(use_case)
    clock.advance(timedelta(minutes=5))
    second = await exchange(use_case)

    assert first.token != second.token
    assert second.expires_at == first.expires_at + timedelta(minutes=5)


# --------------------------------------------------------------- staff: network administrator
# TEN-080, DEC-1260: the owner of a network signs its administrators in through its own directory:
# a group of the owner tenant's directory is mapped to `network-admin`, and the exchange gives that
# role only while the HOST's tenant owns an active network. The registry is asked, not the token.

G_NETWORK = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"


def network_world(**extra: Any) -> _World:
    mappings = [mapping(G_NETWORK, Role.NETWORK_ADMIN), mapping(G_LEAD, Role.LEAD)]
    return world(mappings=mappings, **extra)


async def test_an_owners_network_administrator_gets_the_role_for_the_owners_tenant() -> None:
    ownership = _Ownership("tenant-a")
    built = network_world()

    issued = await exchange(
        staff_use_case(built, accepting(identity(groups=(G_NETWORK,))), ownership=ownership)
    )

    claims = decode_bff_token(issued.token, SIGNING, NOW)
    assert (claims.role, claims.tenant, claims.epoch) == (Role.NETWORK_ADMIN, "tenant-a", 4)
    assert claims.services == frozenset()
    (entry,) = built.audit.entries
    assert entry.snapshot == {"role": "network-admin", "epoch": 4}
    assert ownership.asked == ["tenant-a"]


async def test_the_registry_is_asked_about_the_hosts_tenant_and_no_other() -> None:
    # Tenant B owns a network; the same group on tenant A's host gives nothing.
    ownership = _Ownership("tenant-b")

    with pytest.raises(ExchangeRefused) as refused:
        await exchange(
            staff_use_case(
                network_world(),
                accepting(identity(groups=(G_NETWORK,))),
                ownership=ownership,
            ),
            TENANT_A,
        )

    assert str(refused.value) == EXCHANGE_REFUSED_MESSAGE
    assert ownership.asked == ["tenant-a"]


async def test_a_tenant_that_owns_no_network_gives_the_one_refusal_for_the_role() -> None:
    built = network_world()

    with pytest.raises(ExchangeRefused) as refused:
        await exchange(
            staff_use_case(built, accepting(identity(groups=(G_NETWORK,))), ownership=_Ownership())
        )

    assert str(refused.value) == EXCHANGE_REFUSED_MESSAGE
    assert built.audit.entries == []
    assert all(unit.commits == 0 for unit in built.units)


async def test_a_person_who_also_holds_another_staff_group_falls_to_that_role() -> None:
    issued = await exchange(
        staff_use_case(
            network_world(),
            accepting(identity(groups=(G_NETWORK, G_LEAD))),
            ownership=_Ownership(),
        )
    )

    assert issued.role is Role.LEAD


async def test_without_a_registry_the_role_is_never_given() -> None:
    # A process with no network registry wired fails closed: the role is not given.
    with pytest.raises(ExchangeRefused):
        await exchange(staff_use_case(network_world(), accepting(identity(groups=(G_NETWORK,)))))


async def test_the_registry_is_not_asked_when_the_groups_give_no_network_administrator() -> None:
    ownership = _Ownership("tenant-a")

    issued = await exchange(staff_use_case(network_world(), accepting(), ownership=ownership))

    assert issued.role is Role.LEAD
    assert ownership.asked == []


async def test_a_registry_that_fails_is_a_fault_and_gives_no_token() -> None:
    built = network_world()

    with pytest.raises(ConnectionError):
        await exchange(
            staff_use_case(
                built,
                accepting(identity(groups=(G_NETWORK,))),
                ownership=_Ownership("tenant-a", fail=True),
            )
        )

    assert built.audit.entries == []


async def test_a_retired_network_administrator_mapping_gives_nothing() -> None:
    built = world(mappings=[mapping(G_NETWORK, Role.NETWORK_ADMIN, MappingStatus.RETIRED)])

    with pytest.raises(ExchangeRefused):
        await exchange(
            staff_use_case(
                built,
                accepting(identity(groups=(G_NETWORK,))),
                ownership=_Ownership("tenant-a"),
            )
        )


@pytest.mark.parametrize("claimed", ["network-admin", "DIUCS.NetworkAdmin", "DIUCS.TenantAdmin"])
async def test_a_role_the_identity_claims_is_never_a_network_administrator(claimed: str) -> None:
    # The owner has a network, but the person's GROUPS map to no administrator: an app role the
    # directory's token carries is never read for a staff role.
    built = world(mappings=[mapping(G_LEAD, Role.LEAD)])
    who = identity(groups=(G_OTHER,), app_roles=(claimed,))

    with pytest.raises(ExchangeRefused):
        await exchange(staff_use_case(built, accepting(who), ownership=_Ownership("tenant-a")))


async def test_the_owner_directory_must_be_bound_for_the_owners_own_administrator() -> None:
    # A member of another tenant's directory is no administrator of this owner's network.
    with pytest.raises(ExchangeRefused):
        await exchange(
            staff_use_case(
                network_world(),
                accepting(identity(D_B, groups=(G_NETWORK,))),
                ownership=_Ownership("tenant-a"),
            )
        )


async def test_a_blocked_or_offboarding_owner_gets_no_administrator_token() -> None:
    blocked = make_tenant(
        TenantStatus.SUSPENDED, id="tenant-a", epoch=4, suspend_mode=SuspendMode.BLOCKED
    )

    with pytest.raises(ExchangeRefused):
        await exchange(
            staff_use_case(
                network_world(),
                accepting(identity(groups=(G_NETWORK,))),
                ownership=_Ownership("tenant-a"),
            ),
            blocked,
        )


# ----------------------------------------------------------------------- staff: the binding


async def test_one_directory_bound_to_two_tenants_gives_each_host_its_own_tenant() -> None:
    both = ([verified(D_A)], [mapping(G_LEAD, Role.LEAD)])
    built = world(other=both)

    first = await exchange(staff_use_case(built, accepting()), TENANT_A)
    second = await exchange(staff_use_case(built, accepting()), TENANT_B)

    assert decode_bff_token(first.token, SIGNING, NOW).tenant == "tenant-a"
    assert decode_bff_token(second.token, SIGNING, NOW).tenant == "tenant-b"
    assert decode_bff_token(second.token, SIGNING, NOW).epoch == 2


async def test_a_member_of_another_tenants_directory_gets_nothing_on_this_tenants_host() -> None:
    # Signed in through tenant A's directory, asking on tenant B's host: B's binding is D_B.
    built = world()

    with pytest.raises(ExchangeRefused):
        await exchange(staff_use_case(built, accepting(identity(D_A))), TENANT_B)


REFUSALS: dict[str, Any] = {
    "no binding at all": dict(bindings=[]),
    "a pending binding": dict(
        bindings=[EntraBinding(directory_id=D_A, status=BindingStatus.PENDING)]
    ),
    "a revoked binding": dict(
        bindings=[EntraBinding(directory_id=D_A, status=BindingStatus.REVOKED)]
    ),
    "a binding of another directory": dict(bindings=[verified(D_B)]),
    "no mapping": dict(mappings=[]),
    "a mapping of another group": dict(mappings=[mapping(G_OTHER, Role.LEAD)]),
    "a retired mapping": dict(mappings=[mapping(G_LEAD, Role.LEAD, MappingStatus.RETIRED)]),
}


@pytest.mark.parametrize("name", sorted(REFUSALS))
async def test_every_way_of_not_qualifying_is_the_one_refusal(name: str) -> None:
    built = world(**REFUSALS[name])

    with pytest.raises(ExchangeRefused) as refused:
        await exchange(staff_use_case(built, accepting()))

    assert str(refused.value) == EXCHANGE_REFUSED_MESSAGE
    assert built.audit.entries == []
    assert all(unit.commits == 0 for unit in built.units)


async def test_a_role_the_token_says_is_not_a_role_the_tenant_gave() -> None:
    # The identity claims an app role "DIUCS.Lead"; the tenant's mapping has no group for it.
    built = world(mappings=[])
    who = identity(groups=(), app_roles=("DIUCS.Lead", "DIUCS.Support"))

    with pytest.raises(ExchangeRefused):
        await exchange(staff_use_case(built, accepting(who)))


@pytest.mark.parametrize(
    "tenant",
    [
        make_tenant(TenantStatus.PROVISIONING, id="tenant-a", epoch=4),
        make_tenant(
            TenantStatus.SUSPENDED, id="tenant-a", epoch=4, suspend_mode=SuspendMode.BLOCKED
        ),
        make_tenant(
            TenantStatus.SUSPENDED, id="tenant-a", epoch=4, suspend_mode=SuspendMode.READ_ONLY
        ),
        make_tenant(TenantStatus.OFFBOARDING, id="tenant-a", epoch=4),
        make_tenant(TenantStatus.OFFBOARDED, id="tenant-a", epoch=4),
        make_tenant(TenantStatus.PURGED, id="tenant-a", epoch=4),
    ],
)
async def test_a_tenant_that_may_not_be_signed_into_gives_the_same_refusal(tenant: Tenant) -> None:
    # A read-only suspension is for the administrator's reads: a lead is refused.
    with pytest.raises(ExchangeRefused) as refused:
        await exchange(staff_use_case(world(), accepting()), tenant)

    assert str(refused.value) == EXCHANGE_REFUSED_MESSAGE


async def test_a_credential_the_verifier_rejects_gets_the_same_refusal() -> None:
    verifier = FakeIdentityVerifier()  # accepts nothing

    with pytest.raises(ExchangeRefused) as refused:
        await exchange(staff_use_case(world(), verifier))

    assert str(refused.value) == EXCHANGE_REFUSED_MESSAGE


@pytest.mark.parametrize("credential", ["", "x" * 20000, None, 7, b"bytes"])
async def test_a_credential_that_is_not_a_plausible_token_is_refused(credential: Any) -> None:
    with pytest.raises(ExchangeRefused):
        await exchange(staff_use_case(world(), accepting()), credential=credential)


async def test_a_credential_for_the_operator_audience_is_not_a_staff_credential() -> None:
    verifier = accepting(audience=Audience.OPERATOR)

    with pytest.raises(ExchangeRefused):
        await exchange(staff_use_case(world(), verifier))


async def test_the_refusals_are_all_one_error_class_and_one_message() -> None:
    messages: set[str] = set()
    for name in sorted(REFUSALS):
        with pytest.raises(ExchangeRefused) as refused:
            await exchange(staff_use_case(world(**REFUSALS[name]), accepting()))
        messages.add(str(refused.value))
    with pytest.raises(ExchangeRefused) as refused:
        await exchange(staff_use_case(world(), FakeIdentityVerifier()))
    messages.add(str(refused.value))

    assert messages == {EXCHANGE_REFUSED_MESSAGE}
    assert issubclass(ExchangeRefused, DomainError)
    assert EXCHANGE_REFUSED_MESSAGE == "Your account does not have access."


# ----------------------------------------------------------------------- staff: tenant and unit


async def test_a_unit_that_is_bound_to_another_tenant_than_the_hosts_is_a_wiring_fault() -> None:
    built = world()

    with bind_tenant("tenant-b"), pytest.raises(TenantMismatch):
        await staff_use_case(built, accepting()).execute(
            ExchangeStaffCommand(tenant=TENANT_A, credential=CREDENTIAL)
        )


async def test_nothing_is_bound_by_the_use_case_itself() -> None:
    # The edge binds the host's tenant; with none bound the unit has no scope and nothing resolves.
    with pytest.raises(Exception) as caught:
        await staff_use_case(world(), accepting()).execute(
            ExchangeStaffCommand(tenant=TENANT_A, credential=CREDENTIAL)
        )

    assert not isinstance(caught.value, ExchangeRefused)
    assert current_scope_or_none() is None


# ----------------------------------------------------------------------- staff: audit


async def test_one_audit_entry_in_the_tenants_chain_with_the_role_and_epoch_only() -> None:
    built = world()

    await exchange(staff_use_case(built, accepting()))

    (entry,) = built.audit.entries
    assert (entry.use_case, entry.action) == ("ExchangeStaffToken", "token-issued")
    assert (entry.actor.tenant_id, entry.actor.role) == ("tenant-a", Role.LEAD)
    assert entry.actor.practitioner_id == staff_subject(ACCOUNT_KEY, "tenant-a", D_A, OID)
    assert entry.entity_ids == (staff_subject(ACCOUNT_KEY, "tenant-a", D_A, OID),)
    assert entry.snapshot == {"role": "lead", "epoch": 4}
    assert entry.at == NOW
    assert [unit.commits for unit in built.units] == [1]
    for secret_text in (D_A, OID, G_LEAD, CREDENTIAL):
        assert secret_text not in repr(entry)


async def test_a_failed_audit_gives_no_token() -> None:
    built = world()
    built.audit = _Audit(fail=True)

    with pytest.raises(ConnectionError):
        await exchange(staff_use_case(built, accepting()))


# ----------------------------------------------------------------------- staff: secrets and logs


@pytest.mark.parametrize("missing", [SIGNING_SECRET, ACCOUNT_REF_SECRET])
async def test_a_missing_secret_is_a_configuration_fault_and_not_a_refusal(missing: str) -> None:
    values = {SIGNING_SECRET: SIGNING, ACCOUNT_REF_SECRET: ACCOUNT_KEY}
    del values[missing]

    with pytest.raises(RuntimeError):
        await exchange(staff_use_case(world(), accepting(), FixedSecretStore(values)))


async def test_no_credential_token_or_identity_reaches_a_log_line_or_a_repr(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        issued = await exchange(staff_use_case(world(), accepting()))
        with pytest.raises(ExchangeRefused):
            await exchange(staff_use_case(world(mappings=[]), accepting()))

    for text in (CREDENTIAL, issued.token, D_A, OID, G_LEAD):
        assert text not in caplog.text
        assert text not in repr(issued)
    assert "ExchangeStaffCommand" not in repr(issued)


# ----------------------------------------------------------------------- operator


def operator_use_case(
    verifier: FakeIdentityVerifier,
    store: FixedSecretStore | None = None,
    directory: str = D_OPERATOR,
) -> ExchangeOperatorToken:
    return ExchangeOperatorToken(FixedClock(NOW), verifier, store or secrets(), directory)


def operator_identity(roles: tuple[str, ...] = ("DIUCS.Support",), directory: str = D_OPERATOR):
    return identity(directory, groups=(), app_roles=roles)


async def test_a_support_person_of_the_operators_own_directory_gets_an_operator_token() -> None:
    verifier = accepting(operator_identity(), Audience.OPERATOR)

    issued = await operator_use_case(verifier).execute(
        ExchangeOperatorCommand(credential=CREDENTIAL)
    )

    claims = decode_operator_token(issued.token, SIGNING, NOW)
    assert claims.role is Role.SUPPORT
    assert claims.sub == account_ref(ACCOUNT_KEY, D_OPERATOR, OID)
    assert claims.expires_at == NOW + timedelta(hours=1)
    assert (issued.role, issued.expires_at) == (Role.SUPPORT, NOW + timedelta(hours=1))
    assert verifier.audiences_asked == (Audience.OPERATOR,)


async def test_an_operator_token_is_for_the_operator_audience_and_the_api_refuses_it() -> None:
    verifier = accepting(operator_identity(("DIUCS.PlatformOperator",)), Audience.OPERATOR)

    issued = await operator_use_case(verifier).execute(
        ExchangeOperatorCommand(credential=CREDENTIAL)
    )

    assert OPERATOR_AUDIENCE == "diucs-ops"
    with pytest.raises(TokenRejected):
        decode_bff_token(issued.token, SIGNING, NOW)


async def test_an_operator_role_from_a_customers_directory_is_refused() -> None:
    # A customer's directory administrator can give anyone any app role in it (DEC-134 item 5).
    verifier = accepting(operator_identity(("DIUCS.Support",), directory=D_A), Audience.OPERATOR)

    with pytest.raises(ExchangeRefused) as refused:
        await operator_use_case(verifier).execute(ExchangeOperatorCommand(credential=CREDENTIAL))

    assert str(refused.value) == EXCHANGE_REFUSED_MESSAGE


@pytest.mark.parametrize("roles", [(), ("DIUCS.Advisor",), ("DIUCS.Lead", "support")])
async def test_an_identity_of_the_operators_directory_with_no_operator_role_is_refused(
    roles: tuple[str, ...],
) -> None:
    verifier = accepting(operator_identity(roles), Audience.OPERATOR)

    with pytest.raises(ExchangeRefused):
        await operator_use_case(verifier).execute(ExchangeOperatorCommand(credential=CREDENTIAL))


async def test_a_staff_credential_is_not_an_operator_credential() -> None:
    verifier = accepting(operator_identity(), Audience.STAFF)

    with pytest.raises(ExchangeRefused):
        await operator_use_case(verifier).execute(ExchangeOperatorCommand(credential=CREDENTIAL))


async def test_the_operator_directory_must_be_a_guid() -> None:
    for bad in ("", "tenant-a", D_OPERATOR + "x", None):
        with pytest.raises(ValueError, match="directory"):
            ExchangeOperatorToken(FixedClock(NOW), FakeIdentityVerifier(), secrets(), bad)  # type: ignore[arg-type]


@pytest.mark.parametrize("missing", [SIGNING_SECRET, ACCOUNT_REF_SECRET])
async def test_an_operator_exchange_with_a_missing_secret_is_a_configuration_fault(
    missing: str,
) -> None:
    values = {SIGNING_SECRET: SIGNING, ACCOUNT_REF_SECRET: ACCOUNT_KEY}
    del values[missing]
    verifier = accepting(operator_identity(), Audience.OPERATOR)

    with pytest.raises(RuntimeError):
        await operator_use_case(verifier, FixedSecretStore(values)).execute(
            ExchangeOperatorCommand(credential=CREDENTIAL)
        )


# ----------------------------------------------------------------------- wall screens


DEVICE = Device(
    id="screen-1",
    status=DeviceStatus.ACTIVE,
    name="Ward screen",
    location=None,
    device_type=DeviceType.WALL_DISPLAY,
    token_hash="a" * 64,
    board_scope=BoardScope.TENANT,
)


class _Resolver:
    def __init__(self, found: Device | None) -> None:
        self._found = found
        self.asked: list[str] = []

    async def device(self, token: str) -> Device:
        self.asked.append(token)
        if self._found is None:
            raise EntryRefused
        return self._found


def device_use_case(
    resolver: _Resolver, store: FixedSecretStore | None = None
) -> ExchangeDeviceToken:
    return ExchangeDeviceToken(FixedClock(NOW), resolver, store or secrets())  # type: ignore[arg-type]


async def test_a_paired_screen_gets_a_wall_token_for_the_tenant_of_the_host() -> None:
    resolver = _Resolver(DEVICE)

    issued = await device_use_case(resolver).execute(
        ExchangeDeviceCommand(tenant=TENANT_A, token=DEVICE_TOKEN)
    )

    claims = decode_bff_token(issued.token, SIGNING, NOW)
    assert (claims.role, claims.sub, claims.tenant, claims.epoch) == (
        Role.WALL,
        "screen-1",
        "tenant-a",
        4,
    )
    assert claims.services == frozenset()
    assert claims.expires_at == NOW + timedelta(hours=1)
    assert resolver.asked == [DEVICE_TOKEN]
    assert (issued.role, issued.expires_at) == (Role.WALL, NOW + timedelta(hours=1))


async def test_a_screen_that_does_not_resolve_is_the_uniform_entry_refusal() -> None:
    with pytest.raises(EntryRefused):
        await device_use_case(_Resolver(None)).execute(
            ExchangeDeviceCommand(tenant=TENANT_A, token=DEVICE_TOKEN)
        )


@pytest.mark.parametrize(
    "tenant",
    [
        make_tenant(
            TenantStatus.SUSPENDED, id="tenant-a", epoch=4, suspend_mode=SuspendMode.READ_ONLY
        ),
        make_tenant(
            TenantStatus.SUSPENDED, id="tenant-a", epoch=4, suspend_mode=SuspendMode.BLOCKED
        ),
        make_tenant(TenantStatus.OFFBOARDING, id="tenant-a", epoch=4),
        make_tenant(TenantStatus.PROVISIONING, id="tenant-a", epoch=4),
    ],
)
async def test_a_screen_of_a_tenant_that_is_not_active_gets_the_uniform_refusal(
    tenant: Tenant,
) -> None:
    with pytest.raises(EntryRefused):
        await device_use_case(_Resolver(DEVICE)).execute(
            ExchangeDeviceCommand(tenant=tenant, token=DEVICE_TOKEN)
        )


async def test_a_wall_exchange_with_no_signing_secret_is_a_configuration_fault() -> None:
    with pytest.raises(RuntimeError):
        await device_use_case(_Resolver(DEVICE), FixedSecretStore({})).execute(
            ExchangeDeviceCommand(tenant=TENANT_A, token=DEVICE_TOKEN)
        )


async def test_a_wall_token_is_never_in_a_repr_or_a_log(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        issued = await device_use_case(_Resolver(DEVICE)).execute(
            ExchangeDeviceCommand(tenant=TENANT_A, token=DEVICE_TOKEN)
        )

    assert issued.token not in repr(issued) and DEVICE_TOKEN not in caplog.text
    assert issued.token not in caplog.text
