"""Record builders for the week-summary tests (U35). Each builder makes a plain domain record, so a
test seeds through the ports (the repositories), never through raw Cypher. Values are synthetic:
no names, no phone numbers, no patient data."""

from dataclasses import dataclass
from datetime import datetime

from neo4j import AsyncDriver

from diucs.application.ports.outbound.messaging import Communication
from diucs.domain.codes import (
    BestFitNotUsedReason,
    BookingStatus,
    Channel,
    Measure,
    NeedCategory,
    Outcome,
    ReferrerType,
    ReportSource,
    ReportType,
    Urgency,
)
from diucs.domain.model.booking import Booking
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.case import Case
from diucs.domain.model.scores import News2


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


@dataclass(frozen=True, slots=True)
class SeededWorld:
    service_ids: tuple[str, ...]


async def seed_world(driver: AsyncDriver, tenant: str) -> SeededWorld:
    raise NotImplementedError
