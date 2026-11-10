"""An in-process app for the unit tests of the platform's and the tenant administrator's routes
(TEN-075): no Neo4j, no network.

The services are real use cases over recording stand-ins: the operator's lifecycle over the
provisioning fakes (`tests/support/provisioning_fakes.py`), the support-ticket flow over the real
cross-tenant guard (`tests/support/ticket_rig.py`), and the platform chain as a recording fake. The
tenant administrator's configuration use cases are recording stubs: their rules are unit-tested on
their own, and these tests are about the door, the shapes and what a route refuses before it asks.

The BFF secret store holds the signing secret the operator and tenant doors both verify with
(`bff-jwt`); an operator token is minted with `encode_operator_token`, a tenant token with
`issue_test_token`, and a token of the operator audience that carries a role no operator has is
forged with the module's own sealer, to show that the decoder refuses it.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from overwatch.adapters.inbound.fhir_rest.app import create_app
from overwatch.adapters.inbound.fhir_rest.auth import BFF_SECRET_NAME
from overwatch.adapters.testing.fixed_clock import FixedClock
from overwatch.adapters.testing.fixed_ids import SequentialIds
from overwatch.adapters.testing.fixed_secrets import FixedSecretStore
from overwatch.adapters.testing.memory_cache import InMemoryCache
from overwatch.adapters.testing.recording_senders import RecordingSmsSender
from overwatch.adapters.testing.tokens import TEST_BFF_SECRET, issue_test_token
from overwatch.application.platform_services import (
    PlatformRecorder,
    PlatformServices,
    SupportTicketServices,
    TenantAdminServices,
)
from overwatch.application.ports.outbound.entra_groups import DirectoryMember
from overwatch.application.ports.outbound.platform_audit import PlatformAuditRecord
from overwatch.application.use_cases.admin_consent import AdminConsentView
from overwatch.application.use_cases.entra_groups import (
    InviteResult,
    ManagedGroup,
    ManagedGroups,
    MemberChange,
    ProvisionedGroup,
)
from overwatch.application.use_cases.platform_tenants import ListPlatformTenants, ReadPlatformTenant
from overwatch.application.use_cases.tenant_admin import (
    ActivateTenant,
    CreateTenant,
    RecordTenantNumber,
    RecordTenantReferences,
    RetireTenantNumber,
    SendTestText,
    SetTenantHost,
    UseSharedLine,
    VerifyEntraBinding,
)
from overwatch.application.use_cases.tenant_offboarding import StartTenantOffboarding
from overwatch.application.use_cases.tenant_suspend import SuspendTenant
from overwatch.domain.codes import Role
from overwatch.domain.model.tenant import TenantStatus
from overwatch.domain.rules import bff_token
from overwatch.domain.rules.admin_consent import EffectiveStatus
from overwatch.domain.rules.bff_token import OperatorClaims, encode_operator_token
from tests.support.provisioning_fakes import (
    NOW,
    FakeHeads,
    FakePlatform,
    FakeWorld,
    provisioning_tenant,
)
from tests.support.ticket_rig import REF, Rig, rig

GROUP_A = "aaaaaaaa-0000-4000-8000-00000000000a"
GROUP_B = "aaaaaaaa-0000-4000-8000-00000000000b"
USER_A = "bbbbbbbb-0000-4000-8000-00000000000a"
SIGNING = TEST_BFF_SECRET
SUPPORT_REF = REF
OPERATOR_REF = "ref-platform-operator-0123456"
JSON = {"Content-Type": "application/json"}
KEY = {"Idempotency-Key": "w9c-route-key-0001"}


def operator_token(
    role: Role = Role.PLATFORM_OPERATOR,
    sub: str | None = None,
    expires_at: datetime | None = None,
) -> str:
    reference = sub or (OPERATOR_REF if role is Role.PLATFORM_OPERATOR else SUPPORT_REF)
    return encode_operator_token(
        OperatorClaims(sub=reference, role=role, expires_at=expires_at or NOW + timedelta(hours=1)),
        SIGNING,
    )


def forged_operator_audience_token(role: Role) -> str:
    """A token for the operator door that names a role no operator has: validly signed, and
    refused all the same."""
    body = {
        "sub": "ref-forged-0123456789",
        "role": role.value,
        "aud": bff_token.OPERATOR_AUDIENCE,
        "exp": int((NOW + timedelta(hours=1)).timestamp()),
    }
    return bff_token._sealed(body, SIGNING)


def ops(role: Role = Role.PLATFORM_OPERATOR, **kwargs: Any) -> dict[str, str]:
    return {"Authorization": f"Bearer {operator_token(role, **kwargs)}"}


def tenant_headers(
    role: Role, tenant: str = "tenant-a", sub: str = "admin-ref-0001", **kwargs: Any
) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_test_token(role, [], sub, tenant=tenant, **kwargs)}"}


class Recording:
    """A use case that records its commands and answers a canned result (or raises)."""

    def __init__(self, result: Any = None, error: Exception | None = None) -> None:
        self.commands: list[Any] = []
        self.result = result
        self.error = error

    async def execute(self, command: Any) -> Any:
        self.commands.append(command)
        if self.error is not None:
            raise self.error
        return self.result


class RecordingSearch:
    """The directory search takes the actor and the term, not a command."""

    def __init__(self, result: Any = None, error: Exception | None = None) -> None:
        self.terms: list[Any] = []
        self.result = result
        self.error = error

    async def execute(self, actor: Any, term: Any) -> Any:
        self.terms.append(term)
        if self.error is not None:
            raise self.error
        return self.result


class RecordingChanger(Recording):
    """The membership use case has two entry points; both record into the same list. An
    invitation is recorded apart."""

    def __init__(self, result: Any = None) -> None:
        super().__init__(result)
        self.invitations: list[Any] = []

    async def add(self, command: Any) -> Any:
        return await self.execute(command)

    async def remove(self, command: Any) -> Any:
        return await self.execute(command)

    async def invite(self, command: Any) -> Any:
        self.invitations.append(command)
        if self.error is not None:
            raise self.error
        return InviteResult(GROUP_A, True, True, "0f5a7c1e-3b2d-4c6a-9e8f-1a2b3c4d5e6f")


class FakeAuditReader:
    def __init__(self) -> None:
        self.records: list[PlatformAuditRecord] = []
        self.intact = True
        self.asked: list[tuple[int, int]] = []

    async def entries(self, after_seq: int, limit: int) -> list[PlatformAuditRecord]:
        self.asked.append((after_seq, limit))
        return [r for r in self.records if r.seq > after_seq][:limit]

    async def verify(self) -> bool:
        return self.intact


class FailingAudit:
    def __init__(self) -> None:
        self.entries: list[Any] = []
        self.fail = False

    async def append(self, entry: Any) -> None:
        if self.fail:
            raise ConnectionError("platform audit is down")
        self.entries.append(entry)


class TextLines:
    """The text sender of the test text: one recording sender for every line, the lines it was asked
    for, and the failures a test can ask for (`error` is raised by the resolver, and
    `sender.fail_next()` makes the provider refuse the next text)."""

    def __init__(self) -> None:
        self.sender = RecordingSmsSender("line")
        self.asked: list[Any] = []
        self.error: Exception | None = None

    async def provisioning_sms_for(self, number: Any) -> Any:
        self.asked.append(number)
        if self.error is not None:
            raise self.error
        return self.sender


@dataclass
class Rigs:
    app: FastAPI
    clock: FixedClock
    tickets: Rig
    fake: FakePlatform
    world: FakeWorld
    audit: FailingAudit
    reader: FakeAuditReader
    told: list[str]
    stubs: SimpleNamespace
    platform: PlatformServices
    tenant_admin: TenantAdminServices
    texts: TextLines
    keys: dict[str, str] = field(default_factory=dict)

    def client(self) -> AsyncClient:
        return AsyncClient(
            transport=ASGITransport(app=self.app, raise_app_exceptions=False),
            base_url="http://test",
        )


def build(*, with_services: bool = True) -> Rigs:
    t = rig()
    clock = t.clock
    fake = FakePlatform(
        provisioning_tenant("new-org"),
        provisioning_tenant("act-org", status=TenantStatus.ACTIVE, activated_at=NOW),
    )
    world = FakeWorld()
    audit = FailingAudit()
    reader = FakeAuditReader()
    told: list[str] = []
    ids = SequentialIds()
    texts = TextLines()
    activate = ActivateTenant(
        fake,  # type: ignore[arg-type]
        fake,  # type: ignore[arg-type]
        world.factory(),
        ids,
        clock,
        lambda scope: frozenset({"DT4"}),
    )
    consent_view = AdminConsentView(
        invite_id="inv-1",
        email_masked="j***@example.org",
        status=EffectiveStatus.PENDING,
        created_at=NOW,
        expires_at=NOW + timedelta(days=7),
        consented_at=None,
        reason=None,
    )
    stubs = SimpleNamespace(
        consent_invite=Recording(consent_view),
        consent_read=Recording(consent_view),
        groups_provision=Recording(
            (
                ProvisionedGroup(
                    Role.TENANT_ADMIN, "F81044_overwatch_tenant-admin", GROUP_A, True, True
                ),
                ProvisionedGroup(Role.LEAD, "F81044_overwatch_lead", GROUP_B, False, True),
            )
        ),
        groups_member=Recording(MemberChange(GROUP_A, True)),
        groups_read=Recording(
            ManagedGroups(
                True,
                (
                    ManagedGroup(
                        GROUP_A,
                        "F81044_overwatch_tenant-admin",
                        Role.TENANT_ADMIN,
                        False,
                        (DirectoryMember(USER_A, "Jane Member", "jane@example.org"),),
                    ),
                ),
            )
        ),
        groups_change=RecordingChanger(MemberChange(GROUP_A, True)),
        people_search=RecordingSearch(
            (DirectoryMember(USER_A, "Jane Member", "jane@example.org"),)
        ),
        resume=Recording(
            SimpleNamespace(
                tenant_id="act-org",
                epoch=3,
                services_prompted=2,
                services_announced=2,
                resumed_again=False,
            )
        ),
        reads=Recording(),
        draft=Recording(),
        approve=Recording(),
        contact=Recording(),
        channel=Recording(),
        retention=Recording(),
        bind=Recording(),
        map_group=Recording(),
    )
    ticket_services = SupportTicketServices(
        request=t.request,
        listing=t.listing,
        reading=t.reading,
        cancelling=t.cancelling,
        opening=t.opening,
        using=t.using,
        ending=t.ending,
        approving=t.approving,
        refusing=t.refusing,
        revoking=t.revoking,
    )
    platform = PlatformServices(
        tenants=ListPlatformTenants(fake),  # type: ignore[arg-type]
        detail=ReadPlatformTenant(
            fake,  # type: ignore[arg-type]
            fake,  # type: ignore[arg-type]
            world.factory(),
            clock,
            activate,
        ),
        create=CreateTenant(fake, fake, FakeHeads(), world.factory(), clock),  # type: ignore[arg-type]
        number=RecordTenantNumber(fake, fake, world.factory(), clock),  # type: ignore[arg-type]
        retire=RetireTenantNumber(fake, fake, world.factory(), clock),  # type: ignore[arg-type]
        shared_line=UseSharedLine(fake, world.factory(), clock, available=True),  # type: ignore[arg-type]
        test_text=SendTestText(fake, fake, world.factory(), clock, ids, texts),  # type: ignore[arg-type]
        host=SetTenantHost(fake, fake, world.factory(), clock),  # type: ignore[arg-type]
        references=RecordTenantReferences(fake, fake, world.factory(), clock),  # type: ignore[arg-type]
        directory=VerifyEntraBinding(fake, fake, world.factory(), clock),  # type: ignore[arg-type]
        consent_invite=stubs.consent_invite,  # type: ignore[arg-type]
        consent_read=stubs.consent_read,  # type: ignore[arg-type]
        groups_provision=stubs.groups_provision,  # type: ignore[arg-type]
        groups_member=stubs.groups_member,  # type: ignore[arg-type]
        activate=activate,
        suspend=SuspendTenant(fake, fake, world.factory(), clock, (told.append,)),  # type: ignore[arg-type]
        resume=stubs.resume,  # type: ignore[arg-type]
        offboard=StartTenantOffboarding(fake, fake, world.factory(), clock, (told.append,)),  # type: ignore[arg-type]
        recorder=PlatformRecorder(audit, clock),
        audit_reader=reader,
        tickets=ticket_services,
    )
    tenant_admin = TenantAdminServices(
        reads=stubs.reads,  # type: ignore[arg-type]
        draft=stubs.draft,  # type: ignore[arg-type]
        approve=stubs.approve,  # type: ignore[arg-type]
        contact=stubs.contact,  # type: ignore[arg-type]
        channel=stubs.channel,  # type: ignore[arg-type]
        retention=stubs.retention,  # type: ignore[arg-type]
        bind=stubs.bind,  # type: ignore[arg-type]
        map_group=stubs.map_group,  # type: ignore[arg-type]
        tickets=ticket_services,
        groups_read=stubs.groups_read,  # type: ignore[arg-type]
        groups_change=stubs.groups_change,  # type: ignore[arg-type]
        people_search=stubs.people_search,  # type: ignore[arg-type]
    )
    container = SimpleNamespace(
        clock=clock,
        ids=ids,
        uow_factory=t.world.factory,
        secrets=FixedSecretStore({BFF_SECRET_NAME: SIGNING}),
        tenants=t.directory,
    )
    app = create_app(container)  # type: ignore[arg-type]
    app.state.secrets = FixedSecretStore({BFF_SECRET_NAME: SIGNING})
    app.state.cache = InMemoryCache(clock)
    if with_services:
        app.state.platform_services = platform
        app.state.tenant_admin_services = tenant_admin
    return Rigs(
        app, clock, t, fake, world, audit, reader, told, stubs, platform, tenant_admin, texts
    )


@asynccontextmanager
async def routes() -> AsyncIterator[tuple[Rigs, AsyncClient]]:
    r = build()
    async with r.client() as client:
        yield r, client


NEVER = datetime(2030, 1, 1, tzinfo=UTC)
