"""The refusals of the O08 use cases, which happen before any unit of work or telemetry read
opens."""

from datetime import UTC, date, datetime

import pytest

from diucs.application.use_cases.telemetry_aggregates import BuildDailyAggregates, ReadInsights
from diucs.domain.errors import ValidationFailed


async def test_a_build_refuses_a_datetime_where_a_calendar_day_is_meant() -> None:
    use_case = BuildDailyAggregates(uow_factory=None, telemetry=None)  # type: ignore[arg-type]

    with pytest.raises(ValidationFailed):
        await use_case.execute(datetime(2026, 10, 28, 9, 0, tzinfo=UTC))  # type: ignore[arg-type]


async def test_a_funnel_read_refuses_an_unknown_funnel() -> None:
    reader = ReadInsights(uow_factory=None)  # type: ignore[arg-type]

    with pytest.raises(ValidationFailed):
        await reader.funnel("not-a-funnel", date(2026, 10, 1), date(2026, 10, 28))


async def test_a_range_that_ends_before_it_starts_is_refused() -> None:
    reader = ReadInsights(uow_factory=None)  # type: ignore[arg-type]

    with pytest.raises(ValidationFailed):
        await reader.routes(date(2026, 10, 28), date(2026, 10, 1))
