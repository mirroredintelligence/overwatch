"""A rig for the missed-report ladder tests (U06): one service, its reporters, the use cases that
send a prompt, take a report and run a ladder step, all on one clock and one id generator.

Friday 23 October 2026 is in British Summer Time, so a London wall time is one hour ahead of UTC.
The service reports every 2 hours between 08:00 and 20:00, so the 12:00 prompt is due at 11:00 UTC.
Synthetic values only: no patient data, no real phone number.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, time, timedelta
from typing import Any

from neo4j import AsyncDriver

from diucs.adapters.outbound.content_seal.aes_gcm import AesGcmContentSealer
from diucs.adapters.outbound.graph_store.idempotency_store import DriverIdempotencyStore
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.actor import Actor
from diucs.application.ports.outbound.outbox import OutboxMessage
from diucs.application.ports.outbound.tokens import LinkTokenRepository, LinkTokenService
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.missed_report_ladder import (
    LadderStepCommand,
    LadderStepResult,
    MissedReportLadder,
)
from diucs.application.use_cases.report_capacity import (
    ReportCapacity,
    ReportCapacityCommand,
    ReportCapacityResult,
)
from diucs.application.use_cases.send_prompts import (
    SendPromptCommand,
    SendPromptResult,
    SendPrompts,
    prompt_key,
)
from diucs.application.work import ScheduledWork, WorkKind
from diucs.domain.codes import (
    Cadence,
    Channel,
    Measure,
    PractitionerRoleCode,
    ReportSource,
    ReportType,
    Role,
    ServiceCategory,
)
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.model.service import AvailableTime, ServiceProfile
from tests.support.actors import ACTOR_TENANT
from tests.support.tenancy import as_tenant

SECRET = b"link-token-test-secret-0123456789abcdef"
LINK_BASE = "diucs.example"
PHONE_HASH_1 = "ab" * 32
PHONE_HASH_2 = "cd" * 32

SYSTEM_ACTOR = Actor(
    role=Role.OWNER,
    practitioner_id=None,
    device_id=None,
    channel="worker",
    service_ids=frozenset(),
    tenant_id=ACTOR_TENANT,
)
ADVISOR = Actor(
    role=Role.ADVISOR,
    practitioner_id="advisor-1",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
    tenant_id=ACTOR_TENANT,
)


def london(hour: int, minute: int) -> datetime:
    """A Friday 23 October 2026 London (BST) wall time as a UTC instant."""
    return datetime(2026, 10, 23, hour, minute, tzinfo=UTC) - timedelta(hours=1)


def virtual_ward(service_id: str = "vw-frailty", **changes: Any) -> ServiceProfile:
    profile = ServiceProfile(
        id=service_id,
        name="Virtual ward · frailty",
        category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
        measure=Measure.REFERRALS_ACCEPTABLE,
        unit_label="referrals in the next 2 hrs",
        established_capacity=8,
        can_exceed_established=False,
        usual_range=(0, 8),
        cadence=Cadence.EVERY_2_HRS,
        available_times=(AvailableTime.every_day(time(8, 0), time(20, 0)),),
        channel=Channel.TEXT,
        limited_level_percent=80,
    )
    return replace(profile, **changes)


def reporter(
    number: int,
    phone_hash: str | None,
    service_id: str = "vw-frailty",
    prefix: str = "",
) -> tuple[Practitioner, PractitionerRole]:
    """A reporter and the role that makes them one for the service. `prefix` keeps the ids of two
    tenants apart while the single-property keys of the shared test schema stand (TEN-032)."""
    practitioner = Practitioner(
        id=f"{prefix}prac-{number}",
        active=True,
        display_name=f"Reporter {number}",
        phone_hash=phone_hash,
    )
    role = PractitionerRole(
        id=f"{prefix}role-{number}",
        practitioner_id=practitioner.id,
        service_id=service_id,
        code=PractitionerRoleCode.DUTY_MANAGER,
        active=True,
        channel=Channel.TEXT,
        period_start=datetime(2026, 1, 1, tzinfo=UTC),
    )
    return practitioner, role


async def seed_people(
    factory: UnitOfWorkFactory, *people: tuple[Practitioner, PractitionerRole]
) -> None:
    async with factory() as uow:
        for practitioner, role in people:
            await uow.people.save_practitioner(practitioner)
            await uow.people.save_role(role)
        await uow.commit()


async def seed_report(
    factory: UnitOfWorkFactory,
    effective_at: datetime,
    *,
    service_id: str = "vw-frailty",
    report_id: str = "seed-report-1",
    value: int = 3,
) -> None:
    """A report written straight to the store, as if recorded earlier."""
    async with factory() as uow:
        await uow.capacity.add(
            CapacityReport(
                id=report_id,
                service_id=service_id,
                value=value,
                measure=Measure.REFERRALS_ACCEPTABLE,
                effective_at=effective_at,
                source=ReportSource.TEXT,
                report_type=ReportType.NUMBER,
            )
        )
        await uow.commit()


@dataclass(slots=True)
class Rig:
    factory: UnitOfWorkFactory
    driver: AsyncDriver
    tenant: str
    service_id: str
    clock: FixedClock
    ids: SequentialIds
    sender: SendPrompts
    reports: ReportCapacity
    ladder: MissedReportLadder
    prefix: str = ""

    @property
    def system_actor(self) -> Actor:
        """The actor of the rig's own tenant (a rig of the second tenant must not carry the run
        tenant's actor: the use cases compare the actor's tenant with the bound one)."""
        return replace(SYSTEM_ACTOR, tenant_id=self.tenant)

    async def prompt(self, at: datetime) -> SendPromptResult:
        """Send the prompt that is due at `at`, with the clock at `at`."""
        self.clock.set(at)
        with as_tenant(self.tenant):
            return await self.sender.execute(
                SendPromptCommand(
                    idempotency_key=prompt_key(self.service_id, at),
                    actor=self.system_actor,
                    service_id=self.service_id,
                    due_at=at,
                )
            )

    async def report(
        self,
        at: datetime,
        value: int = 3,
        *,
        effective_at: datetime | None = None,
        key: str | None = None,
        performer: bool = True,
    ) -> ReportCapacityResult:
        """A reporter's text report at `at` (an advisor-phoned report when it is back-dated). The
        performer is the rig's reporter role; a service nobody could be texted for has none to name
        (`performer=False`), and the performer of a report must be a role that exists (TEN-024)."""
        self.clock.set(at)
        back_dated = effective_at is not None
        actor = (
            replace(ADVISOR, tenant_id=self.tenant)
            if back_dated
            else Actor(
                role=Role.REPORTER,
                practitioner_id=f"{self.prefix}prac-1",
                device_id=None,
                channel="sms",
                service_ids=frozenset({self.service_id}),
                tenant_id=self.tenant,
            )
        )
        with as_tenant(self.tenant):
            return await self.reports.execute(
                ReportCapacityCommand(
                    idempotency_key=key or f"report:{self.service_id}:{at.isoformat()}",
                    actor=actor,
                    service_id=self.service_id,
                    value=value,
                    source=ReportSource.ADVISOR_PHONED if back_dated else ReportSource.TEXT,
                    effective_at=effective_at,
                    performer_role_id=(
                        None if back_dated or not performer else f"{self.prefix}role-1"
                    ),
                )
            )

    async def works(self, about_id: str, kind: WorkKind) -> list[ScheduledWork]:
        async with self.factory() as uow:
            return await uow.scheduled_work.for_about(about_id, kind)

    async def work(self, about_id: str, kind: WorkKind) -> ScheduledWork:
        [work] = await self.works(about_id, kind)
        return work

    async def run(
        self, work: ScheduledWork, at: datetime, *, key: str | None = None
    ) -> LadderStepResult:
        """Run one ladder step with the clock at `at`."""
        self.clock.set(at)
        with as_tenant(self.tenant):
            return await self.ladder.execute(
                LadderStepCommand(
                    idempotency_key=key or work.id, actor=self.system_actor, work_id=work.id
                )
            )

    async def step(self, about_id: str, kind: WorkKind, at: datetime) -> LadderStepResult:
        return await self.run(await self.work(about_id, kind), at)

    async def outbox(self) -> list[OutboxMessage]:
        async with self.factory() as uow:
            return await uow.outbox.pending(limit=1000)

    async def events(self, event_type: str) -> list[OutboxMessage]:
        return [m for m in await self.outbox() if m.event_type == event_type]

    def opened(self, message: OutboxMessage) -> dict[str, Any]:
        """The rendered content of one SendMessage, opened as the sender does."""
        sealer = AesGcmContentSealer(FixedSecretStore({"link-token": SECRET}))
        opened: dict[str, Any] = json.loads(
            sealer.unseal(
                message.payload["sealed_content"],
                message_id=message.id,
                tenant_id=self.tenant,
                recipient_role_id=message.payload["recipient_role_id"],
            )
        )
        return opened


def build_rig(
    factory: UnitOfWorkFactory,
    driver: AsyncDriver,
    tenant: str,
    *,
    service_id: str = "vw-frailty",
    start: datetime | None = None,
    ids: SequentialIds | None = None,
    prefix: str = "",
    token_source: Callable[[int], bytes] | None = None,
    clock: FixedClock | None = None,
) -> Rig:
    """`clock` is the clock the rig's use cases run on; a test that has one (an app's container)
    passes it so the rig and the code under test agree on the time (L01)."""
    clock = clock if clock is not None else FixedClock(start or london(12, 0))
    source: dict[str, Any] = {} if token_source is None else {"rng": token_source}
    shared = ids or SequentialIds()

    def tokens(repo: LinkTokenRepository) -> LinkTokenService:
        return LinkTokenService(repo, FixedSecretStore({"link-token": SECRET}), clock, **source)

    sealer = AesGcmContentSealer(FixedSecretStore({"link-token": SECRET}))
    return Rig(
        factory=factory,
        driver=driver,
        tenant=tenant,
        service_id=service_id,
        clock=clock,
        ids=shared,
        sender=SendPrompts(
            factory,
            clock,
            shared,
            DriverIdempotencyStore(driver),
            tokens,
            LINK_BASE,
            sealer,
            tenant,
        ),
        reports=ReportCapacity(factory, clock, shared, DriverIdempotencyStore(driver)),
        ladder=MissedReportLadder(factory, clock, shared, tokens, LINK_BASE, sealer),
        prefix=prefix,
    )
