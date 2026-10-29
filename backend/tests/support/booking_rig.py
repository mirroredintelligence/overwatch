"""Shared rig for the booking lifecycle tests (U18, U19, U20, U36): UCR West accepting 4, one text
reporter, one open case, and a RequestBooking that creates the bookings the tests then act on.

Values are the sample values of the prompts. No patient data: the case stores its district only.
"""

import random
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from neo4j import AsyncDriver

from diucs.adapters.outbound.audit_neo4j.audit_log import ensure_audit_head
from diucs.adapters.outbound.content_seal.aes_gcm import AesGcmContentSealer
from diucs.adapters.outbound.graph_store.idempotency_store import DriverIdempotencyStore
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.actor import Actor
from diucs.application.ports.outbound.tokens import LINK_TOKEN_SECRET, LinkTokenService
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.query_board import QueryBoard
from diucs.application.use_cases.request_booking import (
    RequestBooking,
    RequestBookingCommand,
    RequestBookingResult,
)
from diucs.domain.codes import AgeBand, Channel, NeedCategory, ReferrerType, Role, Urgency
from diucs.domain.model.case import Case
from tests.support.actors import ACTOR_TENANT
from tests.support.ladder_rig import PHONE_HASH_1, reporter, seed_people, seed_report
from tests.support.link_rig import ucr_west

SERVICE_ID = "ucr-west"
SERVICE_NAME = "UCR West"
CASE_ID = "case-1001"
REQUESTED_AT = datetime(2026, 10, 29, 14, 16, tzinfo=UTC)
LINK_HOST = "https://dorset.diucs.example"
SECRETS = FixedSecretStore({LINK_TOKEN_SECRET: b"link-token-test-secret-0123456789abcdef"})

ADVISOR = Actor(
    role=Role.ADVISOR,
    practitioner_id="advisor-1",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
    tenant_id=ACTOR_TENANT,
)
LEAD = Actor(
    role=Role.LEAD,
    practitioner_id="lead-1",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
    tenant_id=ACTOR_TENANT,
)
REPORTER = Actor(
    role=Role.REPORTER,
    practitioner_id="prac-1",
    device_id=None,
    channel="text",
    service_ids=frozenset({SERVICE_ID}),
    tenant_id=ACTOR_TENANT,
)
OTHER_REPORTER = Actor(
    role=Role.REPORTER,
    practitioner_id="prac-9",
    device_id=None,
    channel="text",
    service_ids=frozenset({"ucr-east"}),
    tenant_id=ACTOR_TENANT,
)


def at(hour: int, minute: int) -> datetime:
    return datetime(2026, 10, 29, hour, minute, tzinfo=UTC)


def open_case(case_id: str = CASE_ID, **changes: Any) -> Case:
    references = {"case-1001": "1001", "case-1002": "1002", "case-1003": "1003"}
    case = Case(
        id=case_id,
        reference=references.get(case_id, "1004"),
        referrer_type=ReferrerType.GP,
        age_band=AgeBand.A80_PLUS,
        postcode="DT4",
        needs=(NeedCategory.FALL_NO_INJURY, NeedCategory.FRAILTY),
        urgency=Urgency.WITHIN_2_HRS,
        scores=(),
        opened_at=REQUESTED_AT,
    )
    return replace(case, **changes)


def sealer() -> AesGcmContentSealer:
    return AesGcmContentSealer(SECRETS)


async def seed_world(uow_factory: UnitOfWorkFactory, driver: AsyncDriver) -> None:
    """UCR West with a report at 13:00 of 4, one reporter on text, and one open case."""
    await ensure_audit_head(driver)
    async with uow_factory() as uow:
        await uow.services.save(ucr_west(SERVICE_ID))
        await uow.cases.add(open_case())
        await uow.commit()
    await seed_people(uow_factory, reporter(1, PHONE_HASH_1, service_id=SERVICE_ID))
    await seed_report(uow_factory, at(13, 0), service_id=SERVICE_ID, value=4)


def request_use_case(
    uow_factory: UnitOfWorkFactory, driver: AsyncDriver, now: datetime = REQUESTED_AT
) -> RequestBooking:
    clock = FixedClock(now)

    def tokens(repo: Any) -> LinkTokenService:
        return LinkTokenService(repo, SECRETS, clock)

    return RequestBooking(
        uow_factory,
        DriverIdempotencyStore(driver),
        tokens,
        clock,
        SequentialIds("bk"),
        random.Random(7),
        QueryBoard(uow_factory, clock),
        link_base_url_for=lambda scope: LINK_HOST,
    )


async def request(
    uow_factory: UnitOfWorkFactory,
    driver: AsyncDriver,
    key: str,
    *,
    now: datetime = REQUESTED_AT,
    case_id: str = CASE_ID,
) -> RequestBookingResult:
    command = RequestBookingCommand(
        idempotency_key=key, actor=ADVISOR, case_id=case_id, service_id=SERVICE_ID
    )
    return await request_use_case(uow_factory, driver, now).execute(command)


async def set_reporter_channel(uow_factory: UnitOfWorkFactory, channel: Channel) -> None:
    _, role = reporter(1, PHONE_HASH_1, service_id=SERVICE_ID)
    async with uow_factory() as uow:
        await uow.people.save_role(replace(role, channel=channel))
        await uow.commit()
