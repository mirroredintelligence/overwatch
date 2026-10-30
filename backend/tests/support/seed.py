"""Record builders for the week-summary tests (U35). Each builder makes a plain domain record, so a
test seeds through the ports (the repositories), never through raw Cypher. Values are synthetic:
no names, no phone numbers, no patient data."""

from dataclasses import dataclass
from datetime import datetime, time

from neo4j import AsyncDriver

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.messaging import Communication
from diucs.application.tenancy import ScopeId
from diucs.bootstrap.container import TEST_NOW
from diucs.domain.codes import (
    BestFitNotUsedReason,
    BookingStatus,
    Cadence,
    Channel,
    Measure,
    NeedCategory,
    Outcome,
    ReferrerType,
    ReportSource,
    ReportType,
    ServiceCategory,
    Urgency,
)
from diucs.domain.model.booking import Booking
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.case import Case
from diucs.domain.model.scores import News2
from diucs.domain.model.service import AvailableTime, ServiceProfile
from tests.support.uow import ensure_audit_heads, tenant_uow_factory


def case(
    number: int,
    opened: datetime,
    outcome: Outcome | None = None,
    best_fit: BestFitNotUsedReason | None = None,
) -> Case:
    record = Case(
        id=f"case-{number}",
        reference=f"{1000 + number}",
        referrer_type=ReferrerType.AMBULANCE_CREW,
        age_band=None,
        postcode="DT4",
        needs=(NeedCategory.FRAILTY,),
        urgency=Urgency.TODAY,
        scores=(News2(2),),
        opened_at=opened,
    )
    if outcome is None:
        return record
    return record.close(outcome, at=opened, best_fit_not_used=best_fit)


def report(
    number: int,
    service_id: str,
    at: datetime,
    source: ReportSource = ReportSource.TEXT,
    value: int = 3,
) -> CapacityReport:
    return CapacityReport(
        id=f"obs-{number}",
        service_id=service_id,
        value=value,
        measure=Measure.REFERRALS_ACCEPTABLE,
        effective_at=at,
        source=source,
        report_type=ReportType.NUMBER,
    )


def booking(number: int, service_id: str, requested: datetime, confirmed: datetime) -> Booking:
    return Booking(
        id=f"bk-{number}",
        reference=f"{4000 + number}",
        service_id=service_id,
        case_id=f"case-{number}",
        requester_id="role-requester",
        status=BookingStatus.CONFIRMED,
        requested_at=requested,
        reply_by=requested,
        confirmed_at=confirmed,
    )


def prompt(number: int, service_id: str, sent: datetime) -> Communication:
    return Communication(
        id=f"prompt-{number}",
        message_id="C1",
        channel=Channel.TEXT,
        recipient_role_id=None,
        about_id=service_id,
        payload_text="How many referrals can you take?",
        sent_at=sent,
        delivery_status="sent",
    )


WORLD_SERVICE_IDS = ("svc-ucr-west", "svc-ucr-east")


def world_service(service_id: str, name: str) -> ServiceProfile:
    """A sample urgent community response service: synthetic values, no patient data."""
    return ServiceProfile(
        id=service_id,
        name=name,
        category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
        measure=Measure.REFERRALS_ACCEPTABLE,
        unit_label="referrals",
        established_capacity=8,
        can_exceed_established=False,
        usual_range=(0, 8),
        cadence=Cadence.EVERY_2_HRS,
        available_times=(AvailableTime.every_day(time(8, 0), time(20, 0)),),
        channel=Channel.TEXT,
        limited_level_percent=80,
    )


@dataclass(frozen=True, slots=True)
class SeededWorld:
    """What `seed_world` wrote: the same ids for every tenant."""

    service_ids: tuple[str, ...]


async def seed_world(
    driver: AsyncDriver, tenant: str | ScopeId, clock: Clock | None = None
) -> SeededWorld:
    """Write one sample world into `tenant`: its audit chain head and two urgent community response
    services, through a committed unit of work bound to that tenant. Every tenant gets the same ids
    (`WORLD_SERVICE_IDS`), so a test that seeds two tenants has two worlds that collide on every
    key and can only be told apart by the tenant (DEC-130 item 7). Seeding after the graph was
    wiped (`clean_graph`, which has already made the run tenants' heads) is safe, and so is seeding
    the same tenant twice: a second call stores the same services again."""
    await ensure_audit_heads(driver, tenant)
    factory = tenant_uow_factory(driver, tenant, clock or FixedClock(TEST_NOW))
    async with factory() as uow:
        await uow.services.save(world_service(WORLD_SERVICE_IDS[0], "UCR West"))
        await uow.services.save(world_service(WORLD_SERVICE_IDS[1], "UCR East"))
        await uow.commit()
    return SeededWorld(service_ids=WORLD_SERVICE_IDS)
