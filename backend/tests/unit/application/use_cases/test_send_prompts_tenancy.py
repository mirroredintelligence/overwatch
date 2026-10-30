"""SendPrompts and the tenant (TEN-027, DEC-500; reworks U03 and U04, DEC-115, DEC-156).

No Neo4j. The tenant's time zone and policy reach the rules a prompt uses (the due time is judged in
the tenant's zone, the reply window and the grouping age are the tenant's), the link is the
tenant's own, and the actor's tenant must be the bound one before anything is read. The flow on a
real graph is in `tests/integration/application/test_send_prompts_tenants.py`.
"""

import dataclasses
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.actor import Actor
from diucs.application.tenancy import ScopeId, TenantMismatch, TenantNotBound
from diucs.application.use_cases.send_prompts import (
    SKIP_OUT_OF_HOURS,
    SKIP_REPLY_WINDOW,
    SendPrompts,
    SendPromptCommand,
    _render,
    _skip_reason,
    _too_old_to_confirm,
)
from diucs.domain.codes import (
    Cadence,
    Channel,
    Measure,
    ReportSource,
    ReportType,
    Role,
    ServiceCategory,
)
from diucs.domain.messages.catalogue import MessageId
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.service import AvailableTime, ServiceProfile
from diucs.domain.model.tenant_policy import DEFAULT_POLICY
from diucs.domain.rules.london_time import LONDON
from tests.support.tenancy import as_tenant

NEW_YORK = ZoneInfo("America/New_York")
DUE = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)  # 11:00 in London, 06:00 in New York
PROFILE = ServiceProfile(
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
WINDOW = ("referrals", "in the next 2 hrs")
LATEST = CapacityReport(
    id="obs-1",
    service_id=PROFILE.id,
    value=4,
    measure=PROFILE.measure,
    effective_at=datetime(2026, 7, 1, 9, 0, tzinfo=UTC),
    source=ReportSource.TEXT,
    report_type=ReportType.NUMBER,
)


# -- the zone ------------------------------------------------------------------------------------


def test_a_due_time_is_in_hours_in_the_tenants_zone_only() -> None:
    now = DUE - timedelta(minutes=5)
    assert _skip_reason(PROFILE, False, DUE, now, True, WINDOW, DEFAULT_POLICY, LONDON) is None
    assert (
        _skip_reason(PROFILE, False, DUE, now, True, WINDOW, DEFAULT_POLICY, NEW_YORK)
        == SKIP_OUT_OF_HOURS
    )


def test_the_words_of_the_prompt_are_the_tenants_local_times() -> None:
    reply = DUE + timedelta(minutes=30)
    _, in_london = _render(PROFILE, LATEST, WINDOW, "diucs.example/x", reply, LONDON)
    _, in_new_york = _render(PROFILE, LATEST, WINDOW, "diucs.example/x", reply, NEW_YORK)
    assert "1 Jul 10:00" in in_london.text and "11:30" in in_london.text
    assert "1 Jul 05:00" in in_new_york.text and "06:30" in in_new_york.text


def test_the_first_prompt_words_the_reply_by_in_the_tenants_zone() -> None:
    reply = DUE + timedelta(minutes=30)
    message_id, rendered = _render(PROFILE, None, WINDOW, "diucs.example/x", reply, NEW_YORK)
    assert message_id is MessageId.C2
    assert "06:30" in rendered.text


# -- the policy ----------------------------------------------------------------------------------


def test_the_reply_window_is_the_tenants() -> None:
    short = dataclasses.replace(DEFAULT_POLICY, reply_window=timedelta(minutes=10))
    now = DUE + timedelta(minutes=15)
    assert _skip_reason(PROFILE, False, DUE, now, True, WINDOW, DEFAULT_POLICY, LONDON) is None
    assert _skip_reason(PROFILE, False, DUE, now, True, WINDOW, short, LONDON) == SKIP_REPLY_WINDOW


def test_a_figure_is_too_old_to_confirm_at_the_tenants_limit() -> None:
    now = LATEST.effective_at + timedelta(hours=3)
    assert _too_old_to_confirm(LATEST, now, DEFAULT_POLICY) is True
    longer = dataclasses.replace(DEFAULT_POLICY, stale_warning_after=timedelta(hours=4))
    assert _too_old_to_confirm(LATEST, now, longer) is False
    exactly = LATEST.effective_at + DEFAULT_POLICY.stale_warning_after
    assert _too_old_to_confirm(LATEST, exactly, DEFAULT_POLICY) is False


# -- the tenant of the command -------------------------------------------------------------------


class _Untouched:
    def __init__(self, scope: ScopeId | None) -> None:
        self.unit_scope = scope

    async def __aenter__(self) -> "_Untouched":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the unit of work was touched: {name}")


class _NoStore:
    async def get(self, key: str) -> Any:
        return None

    async def put(self, key: str, value: Any) -> None:
        raise AssertionError("the idempotency store was written")


def _actor(tenant: str) -> Actor:
    return Actor(
        role=Role.OWNER,
        practitioner_id=None,
        device_id=None,
        channel="scheduler",
        service_ids=frozenset(),
        tenant_id=tenant,
    )


def _use_case(scope: ScopeId | None, **extra: Any) -> SendPrompts:
    return SendPrompts(
        lambda: _Untouched(scope),  # type: ignore[arg-type, return-value]
        FixedClock(DUE),
        SequentialIds(),
        _NoStore(),  # type: ignore[arg-type]
        lambda repo: None,  # type: ignore[arg-type, return-value]
        "diucs.example",
        None,  # type: ignore[arg-type]
        **extra,
    )


def _command(tenant: str) -> SendPromptCommand:
    return SendPromptCommand(
        idempotency_key="prompt:svc-daily", actor=_actor(tenant), service_id="svc-daily", due_at=DUE
    )


async def test_an_actor_of_another_tenant_is_refused_before_anything_is_read() -> None:
    with as_tenant("tenant-a"), pytest.raises(TenantMismatch):
        await _use_case(ScopeId.tenant("tenant-a")).execute(_command("tenant-b"))


async def test_with_no_tenant_bound_nothing_is_read() -> None:
    with pytest.raises(TenantNotBound):
        await _use_case(None).execute(_command("tenant-a"))


@pytest.mark.parametrize("scope", [None, ScopeId.network("net-west")], ids=["none", "network"])
async def test_a_unit_that_is_not_a_tenants_is_refused_before_a_read(
    scope: ScopeId | None,
) -> None:
    with as_tenant("tenant-a"), pytest.raises(TenantNotBound):
        await _use_case(scope).execute(_command("tenant-a"))


async def test_a_tenant_named_in_the_constructor_must_be_the_bound_one() -> None:
    """The constructor's tenant is kept for the callers that pass it; it is checked, never used to
    choose a scope."""
    with as_tenant("tenant-a"), pytest.raises(TenantMismatch):
        await _use_case(ScopeId.tenant("tenant-a"), tenant_id="tenant-b").execute(
            _command("tenant-a")
        )

