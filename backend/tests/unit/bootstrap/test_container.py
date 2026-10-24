import dataclasses
from datetime import UTC, datetime

import pytest

from diucs.adapters.outbound.clock_system.system_clock import SystemClock
from diucs.adapters.outbound.ids_uuid.uuid_ids import UuidGenerator
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.bootstrap.container import build, build_for_tests
from diucs.bootstrap.settings import Settings

TEST_NOW = datetime(2026, 10, 23, 13, 0, tzinfo=UTC)


def test_build_wires_the_system_clock_and_uuid_ids() -> None:
    container = build(Settings())
    assert isinstance(container.clock, SystemClock)
    assert isinstance(container.ids, UuidGenerator)


def test_build_for_tests_defaults_to_a_fixed_clock_at_the_test_time() -> None:
    container = build_for_tests()
    assert container.clock.now() == TEST_NOW
    assert isinstance(container.ids, SequentialIds)


def test_build_for_tests_uses_a_clock_that_is_passed_in() -> None:
    later = datetime(2026, 12, 1, 8, 30, tzinfo=UTC)
    container = build_for_tests(clock=FixedClock(later))
    assert container.clock.now() == later


def test_container_is_frozen() -> None:
    container = build_for_tests()
    with pytest.raises(dataclasses.FrozenInstanceError):
        container.clock = SystemClock()  # type: ignore[misc]
