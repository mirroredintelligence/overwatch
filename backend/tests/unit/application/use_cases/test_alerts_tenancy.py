"""The alert evaluator and the tenant's time zone and policy (TEN-027, DEC-500; reworks U34).

No Neo4j: a recording unit of work. Quiet hours are the night of the tenant's own zone, the hours a
service is open are judged in it, and a deputy's default preferences are the tenant's.
"""

from datetime import UTC, datetime, time
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.use_cases.alerts import AlertEvaluator, _alert_subscribers
from diucs.domain.codes import AlertKind, Cadence, Channel, Measure, ServiceCategory
from diucs.domain.model.service import AvailableTime, ServiceProfile
from diucs.domain.rules.alerts import QUIET_END, QUIET_START, Alert, AlertPreferences
from diucs.domain.rules.london_time import LONDON

NEW_YORK = ZoneInfo("America/New_York")
NOW = datetime(2026, 7, 1, 23, 0, tzinfo=UTC)  # 00:00 in London (night), 19:00 in New York
PROFILE = ServiceProfile(
    id="svc-daily",
    name="Daily Service",
    category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
    measure=Measure.REFERRALS_ACCEPTABLE,
    unit_label="referrals",
    established_capacity=8,
    can_exceed_established=False,
    usual_range=(0, 8),
    cadence=Cadence.ONCE_A_DAY,
    available_times=(AvailableTime.every_day(time(9, 0), time(17, 0)),),
    channel=Channel.TEXT,
    limited_level_percent=80,
)
QUIET = AlertPreferences(
    kinds=frozenset(AlertKind),
    not_updated_hours=2,
    quiet_hours=(QUIET_START, QUIET_END),
    quiet_critical_only=True,
    ack_minutes=15,
)


class _Recorder:
    def __init__(self, preferences: AlertPreferences) -> None:
        subscription = SimpleNamespace(preferences=preferences, practitioner_id="prac-1")
        self.added: list[Any] = []
        self.alert_subscriptions = SimpleNamespace(subscribers_for_kind=self._subscribers)
        self._subscription = subscription
        self.alerts = SimpleNamespace(add=self._add)
        self.outbox = SimpleNamespace(add=self._add)
        self.scheduled_work = SimpleNamespace(add=self._add)

    async def _subscribers(self, kind: AlertKind) -> list[Any]:
        return [self._subscription]

    async def _add(self, item: Any) -> None:
        self.added.append(item)


async def _raised(zone: ZoneInfo) -> int:
    uow = _Recorder(QUIET)
    alert = Alert(AlertKind.NOT_UPDATED, PROFILE.id, NOW, False)
    return await _alert_subscribers(uow, SequentialIds(), PROFILE, alert, NOW, zone)  # type: ignore[arg-type]


async def test_a_quiet_night_is_the_tenants_night() -> None:
    assert await _raised(LONDON) == 0
    assert await _raised(NEW_YORK) == 1


def test_the_evaluator_takes_a_zone_source() -> None:
    from diucs.application.tenant_settings import LondonZones

    assert AlertEvaluator(lambda: None, SequentialIds(), zones=LondonZones()) is not None  # type: ignore[arg-type, return-value]
