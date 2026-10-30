"""The link page shows the next prompt in the tenant's own zone and policy (TEN-041, DEC-520).

`CapacityLinkHandler.view` used to call `next_due` with no zone, so the next prompt of every tenant
was worked out in London. It now takes the tenant's zone from the route (the host's tenant record)
and its policy from the configuration in force. The handler runs here against stand-ins for the four
repositories `view` reads; the flow against the real store is in the integration tests.
"""

from datetime import UTC, datetime, time
from types import TracebackType
from typing import Any, Self
from zoneinfo import ZoneInfo

import pytest

from diucs.application.ports.outbound.messaging import Communication
from diucs.application.tenancy import ScopeId
from diucs.application.use_cases.link_access import (
    CAPACITY_PURPOSE,
    CapacityLinkHandler,
    LinkRequest,
    next_due_iso,
)
from diucs.domain.codes import (
    Cadence,
    Channel,
    Measure,
    PractitionerRoleCode,
    ServiceCategory,
)
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.model.service import AvailableTime, ServiceProfile
from diucs.domain.model.tenant_policy import DEFAULT_POLICY
from diucs.domain.rules.london_time import LONDON
from diucs.domain.rules.tokens import LinkTokenRecord

pytestmark = pytest.mark.asyncio(loop_scope="session")

NEW_YORK = ZoneInfo("America/New_York")
NOW = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
PHONE = "f" * 64
SCOPE = ScopeId.tenant("tenant-a")

DAILY = ServiceProfile(
    id="svc-daily",
    name="Daily Service",
    category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
    measure=Measure.REFERRALS_ACCEPTABLE,
    unit_label="referrals in the next 2 hrs",
    established_capacity=8,
    can_exceed_established=False,
    usual_range=(0, 8),
    cadence=Cadence.ONCE_A_DAY,
    available_times=(AvailableTime.every_day(time(9, 0), time(17, 0)),),
    channel=Channel.TEXT,
    limited_level_percent=80,
)
ROLE = PractitionerRole(
    id="role-1",
    practitioner_id="prac-1",
    service_id=DAILY.id,
    code=PractitionerRoleCode.DUTY_MANAGER,
    active=True,
    channel=Channel.TEXT,
    period_start=datetime(2026, 1, 1, tzinfo=UTC),
)


class _Communications:
    async def get(self, communication_id: str) -> Communication:
        return Communication(
            id=communication_id,
            message_id="C1",
            channel=Channel.TEXT,
            recipient_role_id=ROLE.id,
            about_id=DAILY.id,
            payload_text="x",
            sent_at=NOW,
            delivery_status="sent",
        )


class _Services:
    async def get(self, service_id: str) -> ServiceProfile:
        return DAILY


class _People:
    async def find_by_phone_hash(self, phone_hash: str) -> Practitioner:
        return Practitioner(
            id="prac-1", active=True, display_name="Sample Reporter", phone_hash=None
        )

    async def services_for_phone_hash(self, phone_hash: str, now: datetime) -> list[Any]:
        return [(ROLE, DAILY.name)]


class _Capacity:
    async def latest(self, service_id: str) -> None:
        return None


class _Config:
    def __init__(self) -> None:
        self.asked = 0

    async def current_version(self) -> None:
        self.asked += 1
        return None


class _Uow:
    def __init__(self) -> None:
        self.communications = _Communications()
        self.services = _Services()
        self.people = _People()
        self.capacity = _Capacity()
        self.tenant_config = _Config()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None


def _handler(uow: _Uow, **kwargs: Any) -> CapacityLinkHandler:
    return CapacityLinkHandler(
        lambda: uow,  # type: ignore[arg-type,return-value]
        None,  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
        **kwargs,
    )


def _link() -> LinkRequest:
    record = LinkTokenRecord(
        token_hash="a" * 64,
        purpose=CAPACITY_PURPOSE,
        about_id="c-1",
        phone_hash=PHONE,
        expires_at=datetime(2026, 7, 1, 12, 30, tzinfo=UTC),
        used_at=None,
    )
    return LinkRequest(record=record, token="x" * 23, scope=SCOPE, now=NOW)


def test_the_next_prompt_is_worked_out_in_the_zone_given() -> None:
    assert next_due_iso(DAILY, NOW, DEFAULT_POLICY, LONDON) == "2026-07-02T08:00:00Z"
    assert next_due_iso(DAILY, NOW, DEFAULT_POLICY, NEW_YORK) == "2026-07-01T13:00:00Z"


def test_a_service_with_no_next_prompt_has_none(monkeypatch: pytest.MonkeyPatch) -> None:
    from diucs.application.use_cases import link_access

    monkeypatch.setattr(link_access, "next_due", lambda *args, **kwargs: None)

    assert next_due_iso(DAILY, NOW, DEFAULT_POLICY, LONDON) is None


async def test_the_page_shows_the_next_prompt_in_the_zone_the_route_passed() -> None:
    page_london = await _handler(_Uow(), zone=LONDON).view(_link())
    page_new_york = await _handler(_Uow(), zone=NEW_YORK).view(_link())

    assert page_london["nextDue"] == "2026-07-02T08:00:00Z"
    assert page_new_york["nextDue"] == "2026-07-01T13:00:00Z"


async def test_the_page_reads_the_tenants_configuration_for_its_policy() -> None:
    uow = _Uow()

    await _handler(uow, zone=LONDON).view(_link())

    assert uow.tenant_config.asked == 1


async def test_a_handler_built_with_no_zone_works_in_londons_zone() -> None:
    # The route always passes the tenant's zone; a caller that does not know a tenant (a rig) gets
    # the one zone the allow-list holds today.
    page = await _handler(_Uow()).view(_link())

    assert page["nextDue"] == "2026-07-02T08:00:00Z"


def test_the_ratchet_no_longer_lists_link_access() -> None:
    from tests.unit.domain.rules.test_zone_threading import ZONE_NOT_YET_THREADED

    assert "application/use_cases/link_access.py" not in ZONE_NOT_YET_THREADED
