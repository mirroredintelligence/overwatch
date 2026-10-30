"""The fixture fake's daily summary: one tenant's rows of one day, never another tenant's (O08)."""

from datetime import date
from pathlib import Path

import pytest

from diucs.adapters.testing.fixture_telemetry import FixtureTelemetryQuery
from diucs.application.tenancy import ScopeId, TenantNotBound, bind_scope

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures" / "telemetry" / "s-7f3a.json"
DAY = date(2026, 10, 28)


def _query() -> FixtureTelemetryQuery:
    return FixtureTelemetryQuery(FIXTURE, attributes=lambda attrs: dict(attrs))


async def test_the_bound_tenant_gets_its_own_day() -> None:
    with bind_scope(ScopeId.tenant("test-a")):
        day = await _query().daily_aggregates(DAY)

    assert len(day.funnel) == 6
    assert {row.element_id for row in day.friction} == {"ADV-OPT-REQUEST-BTN", "ADV-REF-INPUT"}
    assert all(row.day == DAY for row in day.routes)


async def test_another_tenant_never_sees_these_rows() -> None:
    with bind_scope(ScopeId.tenant("test-b")):
        day = await _query().daily_aggregates(DAY)

    assert [row.element_id for row in day.friction] == ["B-ONLY-BTN"]
    assert "ADV-OPT-REQUEST-BTN" not in {row.element_id for row in day.usage}


async def test_a_day_with_no_telemetry_is_empty_not_an_error() -> None:
    with bind_scope(ScopeId.tenant("test-a")):
        day = await _query().daily_aggregates(date(2026, 1, 1))

    assert day.funnel == () and day.friction == () and day.queries == ()


async def test_no_tenant_bound_is_refused() -> None:
    with pytest.raises(TenantNotBound):
        await _query().daily_aggregates(DAY)
