"""The cross-tenant support guard, end to end against stand-ins (TEN-084, DEC-528 to DEC-533).

A tenant's administrator issues a code. A platform support person (a principal from the operator
directory) opens ONE tenant with that code and gets an access that lasts an hour. Every use of the
access is checked against the tenant and the person and written to the tenant's own audit chain and
to the platform chain. Everything else is denied: the platform operator, a tenant's own roles, a
code of another tenant, a code used twice, a suspended tenant, an expired access. The cache holds
the code's hash and the access (nothing of record: losing it denies, never allows); the audit is the
record.

The unit of work, the cache (the in-memory fake, which qualifies every name by the bound tenant like
Redis does), the tenant directory and the platform audit are stand-ins that record what they were
asked; nothing reaches a store.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Any, Self

import pytest
from diucs.adapters.testing.recording_platform_audit import RecordingPlatformAudit
from diucs.application.cross_tenant_guard import (
    ACCESS_VALID_FOR,
    CODE_VALID_FOR,
    AuthoriseCommand,
    CrossTenantDenied,
    CrossTenantGuard,
    EndAccessCommand,
    IssueCodeCommand,
    OpenAccessCommand,
    PlatformPrincipal,
    RevokeAccessCommand,
)

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.identity import TenantKeyedSecrets
from diucs.application.tenancy import ScopeId, TenantMismatch, bind_tenant, current_scope_or_none
from diucs.domain.codes import Role
from diucs.domain.model.tenant import SuspendMode, Tenant, TenantStatus
from diucs.domain.rules.support import SUPPORT_CODE_SECRET
from tests.support.tenant_samples import make_tenant

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
PLATFORM_KEY = b"synthetic-platform-key-for-the-guard-unit-tests-01"
REF = "ref-support-person-0123456789"
OTHER_REF = "ref-another-support-9876543210"
PRINCIPAL = PlatformPrincipal(account_ref=REF, role=Role.SUPPORT)
OTHER_PRINCIPAL = PlatformPrincipal(account_ref=OTHER_REF, role=Role.SUPPORT)


# ----------------------------------------------------------------------- stand-ins


class _Audit:
    def __init__(self, world: _World) -> None:
        self._world = world

    async def append(self, entry: AuditEntry) -> None:
        if self._world.fail_tenant_audit:
            raise ConnectionError("audit store down")
        self._world.pending.append(entry)


class _Uow:
    def __init__(self, world: _World) -> None:
        self.audit = _Audit(world)
        self._world = world
        self._scope = current_scope_or_none()
        world.units.append(self)

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
        assert self._scope is not None
        self._world.chains.setdefault(self._scope.value, []).extend(self._world.pending)
        self._world.pending.clear()


class _Directory:
    def __init__(self, tenants: dict[str, Tenant]) -> None:
        self.tenants = tenants

    async def get(self, tenant_id: str) -> Tenant | None:
        return self.tenants.get(tenant_id)


@dataclass
class _World:
    chains: dict[str, list[AuditEntry]] = field(default_factory=dict)
    pending: list[AuditEntry] = field(default_factory=list)
    units: list[_Uow] = field(default_factory=list)
    fail_tenant_audit: bool = False

    def factory(self) -> _Uow:
        return _Uow(self)

    def chain(self, tenant: str) -> list[AuditEntry]:
        return self.chains.get(tenant, [])


@dataclass
class _Rig:
    guard: CrossTenantGuard
    world: _World
    cache: InMemoryCache
    clock: FixedClock
    platform: RecordingPlatformAudit
    directory: _Directory


def rig(tenants: dict[str, Tenant] | None = None) -> _Rig:
    clock = FixedClock(NOW)
    world = _World()
    cache = InMemoryCache(clock)
    platform = RecordingPlatformAudit()
    directory = _Directory(
        tenants
        or {
            "tenant-a": make_tenant(id="tenant-a"),
            "tenant-b": make_tenant(id="tenant-b"),
        }
    )
    guard = CrossTenantGuard(
        world.factory,  # type: ignore[arg-type]
        cache,
        clock,
        SequentialIds("access"),
        TenantKeyedSecrets(FixedSecretStore({SUPPORT_CODE_SECRET: PLATFORM_KEY})),
        directory,  # type: ignore[arg-type]
        platform,
    )
    return _Rig(guard, world, cache, clock, platform, directory)


def admin(tenant: str = "tenant-a", role: Role = Role.TENANT_ADMIN) -> Actor:
    return Actor(
        role=role,
        practitioner_id="admin-1",
        device_id=None,
        channel="api",
        service_ids=frozenset(),
        tenant_id=tenant,
    )


async def issue(r: _Rig, tenant: str = "tenant-a") -> str:
    with bind_tenant(tenant):
        issued = await r.guard.issue_code(IssueCodeCommand(actor=admin(tenant)))
    return issued.code


async def open_access(
    r: _Rig, code: str, tenant: str = "tenant-a", principal: PlatformPrincipal = PRINCIPAL
) -> Any:
    return await r.guard.open(OpenAccessCommand(principal=principal, tenant_id=tenant, code=code))


async def authorise(
    r: _Rig,
    access_id: str,
    tenant: str = "tenant-a",
    principal: PlatformPrincipal = PRINCIPAL,
    action: str = "read-session",
) -> Any:
    return await r.guard.authorise(
        AuthoriseCommand(principal=principal, tenant_id=tenant, access_id=access_id, action=action)
    )


def actions(entries: list[Any]) -> list[str]:
    return [entry.action for entry in entries]


# ----------------------------------------------------------------------- issuing a code


async def test_the_tenants_administrator_issues_a_code_that_lasts_four_hours() -> None:
    r = rig()

    with bind_tenant("tenant-a"):
        issued = await r.guard.issue_code(IssueCodeCommand(actor=admin()))

    assert len(issued.code) == 9 and issued.code[4] == "-"
    assert issued.expires_at == NOW + CODE_VALID_FOR
    (entry,) = r.world.chain("tenant-a")
    assert (entry.use_case, entry.action) == (
        "IssueSupportAccessCode",
        "support-access-code-issued",
    )
    assert (entry.actor.role, entry.actor.practitioner_id) == (Role.TENANT_ADMIN, "admin-1")
    assert entry.snapshot == {"expires_at": NOW + CODE_VALID_FOR}
    assert r.platform.entries == []


async def test_the_cache_holds_the_codes_hash_in_the_tenants_own_names_and_never_the_code() -> None:
    r = rig()
    code = await issue(r)

    with bind_tenant("tenant-a"):
        keys_a = r.cache.keys()
        stored = [await r.cache.get(key.split(":cache:", 1)[1]) for key in keys_a]
    with bind_tenant("tenant-b"):
        keys_b = r.cache.keys()

    assert len(keys_a) == 1 and keys_b == frozenset()
    assert all(
        code not in (text or "") and code.replace("-", "") not in (text or "") for text in stored
    )
    assert code not in repr(r.world.chain("tenant-a")[0])


@pytest.mark.parametrize("role", [r for r in Role if r is not Role.TENANT_ADMIN])
async def test_no_other_role_may_issue_and_nothing_is_written(role: Role) -> None:
    r = rig()

    with bind_tenant("tenant-a"), pytest.raises(CrossTenantDenied):
        await r.guard.issue_code(IssueCodeCommand(actor=admin(role=role)))

    assert r.world.chain("tenant-a") == []
    with bind_tenant("tenant-a"):
        assert r.cache.keys() == frozenset()


async def test_an_actor_of_another_tenant_than_the_one_bound_is_a_wiring_fault() -> None:
    r = rig()

    with bind_tenant("tenant-a"), pytest.raises(TenantMismatch):
        await r.guard.issue_code(IssueCodeCommand(actor=admin("tenant-b")))


async def test_a_failed_audit_gives_no_code_and_leaves_no_grant() -> None:
    r = rig()
    r.world.fail_tenant_audit = True

    with bind_tenant("tenant-a"):
        with pytest.raises(ConnectionError):
            await r.guard.issue_code(IssueCodeCommand(actor=admin()))
        assert r.cache.keys() == frozenset()


async def test_a_cache_that_cannot_be_reached_gives_no_code() -> None:
    r = rig()

    async def down(*args: Any, **kwargs: Any) -> bool:
        raise ConnectionError("cache is down")

    r.cache.set_if_absent = down  # type: ignore[method-assign]
    with bind_tenant("tenant-a"), pytest.raises(ConnectionError):
        await r.guard.issue_code(IssueCodeCommand(actor=admin()))

    assert r.world.chain("tenant-a") == []


# ----------------------------------------------------------------------- opening an access


async def test_a_support_person_opens_one_tenant_with_the_code_for_an_hour() -> None:
    r = rig()
    code = await issue(r)

    elevation = await open_access(r, code)

    assert (elevation.tenant_id, elevation.principal_ref) == ("tenant-a", REF)
    assert elevation.opened_at == NOW
    assert elevation.expires_at == NOW + ACCESS_VALID_FOR
    opened = r.world.chain("tenant-a")[-1]
    assert (opened.use_case, opened.action) == ("OpenCrossTenantAccess", "support-access-opened")
    assert (opened.actor.role, opened.actor.practitioner_id) == (Role.SUPPORT, REF)
    assert opened.actor.tenant_id == "tenant-a"
    assert opened.entity_ids == (elevation.access_id,)
    (platform,) = r.platform.entries
    assert (platform.action, platform.tenant_id, platform.principal_ref) == (
        "support-access-opened",
        "tenant-a",
        REF,
    )
    assert platform.access_id == elevation.access_id
    assert r.world.chain("tenant-b") == []


async def test_the_code_may_be_typed_with_spaces_hyphens_and_lower_case() -> None:
    r = rig()
    code = await issue(r)

    elevation = await open_access(r, code.replace("-", " ").lower())

    assert elevation.tenant_id == "tenant-a"


async def test_a_code_of_one_tenant_opens_nothing_in_another() -> None:
    r = rig()
    code = await issue(r, "tenant-a")

    with pytest.raises(CrossTenantDenied):
        await open_access(r, code, "tenant-b")

    assert r.world.chain("tenant-b") == []
    assert actions(r.platform.entries) == ["support-access-refused"]
    assert r.platform.entries[0].tenant_id == "tenant-b"


async def test_a_code_opens_one_access_and_only_one() -> None:
    r = rig()
    code = await issue(r)
    first = await open_access(r, code)

    with pytest.raises(CrossTenantDenied):
        await open_access(r, code)
    with pytest.raises(CrossTenantDenied):
        await open_access(r, code, principal=OTHER_PRINCIPAL)

    assert (await authorise(r, first.access_id)).access_id == first.access_id


async def test_two_opens_at_once_let_exactly_one_through() -> None:
    r = rig()
    code = await issue(r)

    results = await asyncio.gather(
        *(open_access(r, code) for _ in range(8)), return_exceptions=True
    )

    assert sum(1 for result in results if not isinstance(result, Exception)) == 1
    assert all(
        isinstance(result, CrossTenantDenied) for result in results if isinstance(result, Exception)
    )
    assert actions(r.world.chain("tenant-a")).count("support-access-opened") == 1


@pytest.mark.parametrize("code", ["", "not a code", "ABCD-EFGH", "ABCD-EFG", "0000-0000", None, 7])
async def test_a_code_nobody_issued_is_refused(code: object) -> None:
    r = rig()
    await issue(r)

    with pytest.raises(CrossTenantDenied):
        await open_access(r, code)  # type: ignore[arg-type]


async def test_a_code_that_has_expired_is_refused() -> None:
    r = rig()
    code = await issue(r)
    r.clock.advance(CODE_VALID_FOR)

    with pytest.raises(CrossTenantDenied):
        await open_access(r, code)


async def test_an_access_opened_late_in_the_codes_life_ends_with_the_code() -> None:
    r = rig()
    code = await issue(r)
    r.clock.advance(timedelta(hours=3, minutes=30))

    elevation = await open_access(r, code)

    assert elevation.expires_at == NOW + CODE_VALID_FOR


@pytest.mark.parametrize(
    "tenant",
    [
        make_tenant(TenantStatus.PROVISIONING, id="tenant-a"),
        make_tenant(TenantStatus.SUSPENDED, id="tenant-a", suspend_mode=SuspendMode.READ_ONLY),
        make_tenant(TenantStatus.SUSPENDED, id="tenant-a", suspend_mode=SuspendMode.BLOCKED),
        make_tenant(TenantStatus.OFFBOARDING, id="tenant-a"),
        make_tenant(TenantStatus.PURGED, id="tenant-a"),
    ],
)
async def test_a_tenant_that_is_not_active_cannot_be_accessed(tenant: Tenant) -> None:
    r = rig()
    code = await issue(r)
    r.directory.tenants["tenant-a"] = tenant

    with pytest.raises(CrossTenantDenied):
        await open_access(r, code)

    assert actions(r.world.chain("tenant-a")) == ["support-access-code-issued"]


async def test_a_tenant_that_does_not_exist_is_refused_the_same_way() -> None:
    r = rig()

    with pytest.raises(CrossTenantDenied) as unknown:
        await open_access(r, "ABCD-EFGH", "no-such-tenant")
    with pytest.raises(CrossTenantDenied) as wrong_code:
        await open_access(r, "ABCD-EFGH", "tenant-a")

    assert str(unknown.value) == str(wrong_code.value)


@pytest.mark.parametrize("tenant", ["", "net-region-1", "platform", "Tenant A", None, 7])
async def test_a_tenant_that_is_not_a_tenant_id_is_refused_before_anything_is_looked_up(
    tenant: object,
) -> None:
    r = rig()

    with pytest.raises(CrossTenantDenied):
        await open_access(r, "ABCD-EFGH", tenant)  # type: ignore[arg-type]

    assert r.world.units == []


async def test_every_refusal_is_one_error_with_one_message_and_a_platform_note() -> None:
    r = rig()
    code = await issue(r)
    messages: set[str] = set()
    for tenant, attempt in (
        ("tenant-b", code),
        ("tenant-a", "ABCD-EFGH"),
        ("no-such-tenant", code),
        ("tenant-a", "garbage"),
    ):
        with pytest.raises(CrossTenantDenied) as refused:
            await open_access(r, attempt, tenant)
        messages.add(str(refused.value))

    assert len(messages) == 1
    assert actions(r.platform.entries) == ["support-access-refused"] * 4
    assert [e.snapshot for e in r.platform.entries] == [
        {"reason": "no-grant"},
        {"reason": "no-grant"},
        {"reason": "tenant"},
        {"reason": "code"},
    ]
    assert [e.tenant_id for e in r.platform.entries] == [
        "tenant-b",
        "tenant-a",
        "no-such-tenant",
        "tenant-a",
    ]
    assert all(e.principal_ref == REF and e.access_id is None for e in r.platform.entries)
    for chain in r.world.chains.values():
        assert "support-access-refused" not in actions(chain)


async def test_a_failure_of_the_platform_audit_opens_nothing_and_frees_the_code() -> None:
    r = rig()
    code = await issue(r)
    r.platform.fail_next = True

    with pytest.raises(ConnectionError):
        await open_access(r, code)

    with bind_tenant("tenant-a"):
        assert len(r.cache.keys()) == 1  # the grant only: no claim, no access
    again = await open_access(r, code)
    assert again.tenant_id == "tenant-a"


async def test_a_failure_of_the_tenant_audit_opens_nothing_and_leaves_a_platform_note() -> None:
    r = rig()
    code = await issue(r)
    r.world.fail_tenant_audit = True

    with pytest.raises(ConnectionError):
        await open_access(r, code)

    with bind_tenant("tenant-a"):
        assert len(r.cache.keys()) == 1
    assert actions(r.platform.entries) == ["support-access-opened", "support-access-aborted"]
    r.world.fail_tenant_audit = False
    assert (await open_access(r, code)).tenant_id == "tenant-a"


async def test_nothing_is_left_bound_after_an_open() -> None:
    r = rig()
    code = await issue(r)

    await open_access(r, code)

    assert current_scope_or_none() is None


async def test_the_code_and_the_access_never_reach_a_log_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    r = rig()
    with caplog.at_level(logging.DEBUG):
        code = await issue(r)
        elevation = await open_access(r, code)
        with pytest.raises(CrossTenantDenied):
            await open_access(r, code)
        await authorise(r, elevation.access_id)

    assert code not in caplog.text and code.replace("-", "") not in caplog.text
    assert elevation.access_id not in caplog.text and REF not in caplog.text


# ----------------------------------------------------------------------- using an access


async def test_a_use_of_the_access_is_audited_in_both_chains() -> None:
    r = rig()
    elevation = await open_access(r, await issue(r))

    held = await authorise(r, elevation.access_id, action="read-session")

    assert held.access_id == elevation.access_id
    used = r.world.chain("tenant-a")[-1]
    assert (used.use_case, used.action) == ("UseCrossTenantAccess", "support-access-used")
    assert used.entity_ids == (elevation.access_id,)
    assert used.snapshot == {"action": "read-session"}
    assert used.actor.practitioner_id == REF
    platform = r.platform.entries[-1]
    assert (platform.action, platform.access_id, platform.tenant_id) == (
        "support-access-used",
        elevation.access_id,
        "tenant-a",
    )
    assert platform.snapshot == {"action": "read-session"}


async def test_an_access_stops_standing_at_the_hour() -> None:
    r = rig()
    elevation = await open_access(r, await issue(r))
    r.clock.advance(ACCESS_VALID_FOR - timedelta(seconds=1))
    await authorise(r, elevation.access_id)
    r.clock.advance(timedelta(seconds=1))
    used_before = len(r.world.chain("tenant-a"))

    with pytest.raises(CrossTenantDenied):
        await authorise(r, elevation.access_id)

    assert len(r.world.chain("tenant-a")) == used_before  # a denial writes nothing to the tenant
    assert r.platform.entries[-1].action == "support-access-refused"
    assert r.platform.entries[-1].snapshot == {"reason": "no-access"}


async def test_another_support_person_cannot_use_the_access() -> None:
    r = rig()
    elevation = await open_access(r, await issue(r))

    with pytest.raises(CrossTenantDenied):
        await authorise(r, elevation.access_id, principal=OTHER_PRINCIPAL)


async def test_an_access_to_one_tenant_is_no_access_to_another() -> None:
    r = rig()
    elevation = await open_access(r, await issue(r, "tenant-a"))

    with pytest.raises(CrossTenantDenied):
        await authorise(r, elevation.access_id, tenant="tenant-b")

    assert r.world.chain("tenant-b") == []


@pytest.mark.parametrize("access_id", ["", "no-such-access", "x" * 600, None, 7])
async def test_an_access_nobody_opened_is_denied(access_id: object) -> None:
    r = rig()
    await open_access(r, await issue(r))

    with pytest.raises(CrossTenantDenied):
        await authorise(r, access_id)  # type: ignore[arg-type]


async def test_a_damaged_access_in_the_cache_is_denied_and_never_allowed() -> None:
    r = rig()
    elevation = await open_access(r, await issue(r))
    with bind_tenant("tenant-a"):
        await r.cache.set(f"support-access:{elevation.access_id}", "not json", timedelta(hours=1))

    with pytest.raises(CrossTenantDenied):
        await authorise(r, elevation.access_id)


async def test_losing_the_cache_ends_every_access() -> None:
    r = rig()
    elevation = await open_access(r, await issue(r))
    with bind_tenant("tenant-a"):
        await r.cache.delete(f"support-access:{elevation.access_id}")

    with pytest.raises(CrossTenantDenied):
        await authorise(r, elevation.access_id)


async def test_a_call_is_not_allowed_if_its_audit_cannot_be_written() -> None:
    r = rig()
    elevation = await open_access(r, await issue(r))
    r.world.fail_tenant_audit = True

    with pytest.raises(ConnectionError):
        await authorise(r, elevation.access_id)


async def test_a_call_is_not_allowed_if_the_platform_audit_cannot_be_written() -> None:
    r = rig()
    elevation = await open_access(r, await issue(r))
    r.platform.fail_next = True

    with pytest.raises(ConnectionError):
        await authorise(r, elevation.access_id)


@pytest.mark.parametrize("action", ["", "Read", "read session", "x" * 41, None])
async def test_an_action_that_is_not_a_word_is_refused(action: object) -> None:
    r = rig()
    elevation = await open_access(r, await issue(r))

    with pytest.raises(Exception) as refused:
        await authorise(r, elevation.access_id, action=action)  # type: ignore[arg-type]

    assert not isinstance(refused.value, ConnectionError)


# ----------------------------------------------------------------------- ending an access


async def test_the_support_person_ends_the_access_and_it_stops_standing() -> None:
    r = rig()
    elevation = await open_access(r, await issue(r))

    await r.guard.end(
        EndAccessCommand(principal=PRINCIPAL, tenant_id="tenant-a", access_id=elevation.access_id)
    )

    with pytest.raises(CrossTenantDenied):
        await authorise(r, elevation.access_id)
    assert r.world.chain("tenant-a")[-1].action == "support-access-ended"
    assert r.platform.entries[-1].action == "support-access-ended"


async def test_another_support_person_cannot_end_the_access() -> None:
    r = rig()
    elevation = await open_access(r, await issue(r))

    with pytest.raises(CrossTenantDenied):
        await r.guard.end(
            EndAccessCommand(
                principal=OTHER_PRINCIPAL, tenant_id="tenant-a", access_id=elevation.access_id
            )
        )

    assert (await authorise(r, elevation.access_id)).access_id == elevation.access_id


async def test_the_tenants_administrator_can_end_an_access_to_their_own_tenant() -> None:
    r = rig()
    elevation = await open_access(r, await issue(r))

    with bind_tenant("tenant-a"):
        await r.guard.revoke(RevokeAccessCommand(actor=admin(), access_id=elevation.access_id))

    with pytest.raises(CrossTenantDenied):
        await authorise(r, elevation.access_id)
    ended = r.world.chain("tenant-a")[-1]
    assert (ended.action, ended.actor.role) == ("support-access-revoked", Role.TENANT_ADMIN)
    assert r.platform.entries[-1].action == "support-access-revoked"
    assert r.platform.entries[-1].principal_ref == REF


async def test_another_tenants_administrator_cannot_end_the_access() -> None:
    r = rig()
    elevation = await open_access(r, await issue(r, "tenant-a"))

    with bind_tenant("tenant-b"), pytest.raises(CrossTenantDenied):
        await r.guard.revoke(
            RevokeAccessCommand(actor=admin("tenant-b"), access_id=elevation.access_id)
        )

    assert (await authorise(r, elevation.access_id)).access_id == elevation.access_id


@pytest.mark.parametrize("role", [r for r in Role if r is not Role.TENANT_ADMIN])
async def test_no_other_role_can_revoke(role: Role) -> None:
    r = rig()
    elevation = await open_access(r, await issue(r))

    with bind_tenant("tenant-a"), pytest.raises(CrossTenantDenied):
        await r.guard.revoke(
            RevokeAccessCommand(actor=admin(role=role), access_id=elevation.access_id)
        )
