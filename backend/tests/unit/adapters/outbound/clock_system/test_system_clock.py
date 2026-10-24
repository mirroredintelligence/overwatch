from datetime import UTC, datetime, timedelta

from diucs.adapters.outbound.clock_system.system_clock import SystemClock


def test_system_clock_returns_utc_now() -> None:
    before = datetime.now(UTC)
    now = SystemClock().now()
    after = datetime.now(UTC)

    assert now.tzinfo is UTC
    assert now.utcoffset() == timedelta(0)
    assert before <= now <= after
