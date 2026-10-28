"""A per-test time limit that needs no new dependency (F10b, DEC-135).

Lesson L67: a run stalled on its first Neo4j test for over nine minutes and nothing ended it. The
limit is a SIGALRM watchdog in the root conftest, built on tests/support/watchdog.py. A test that
hangs fails with a message that names it and shows where it was; the next test still runs.
"""

import signal
import time
from pathlib import Path

import pytest

from tests.support.watchdog import (
    DEFAULT_TEST_TIMEOUT_S,
    TimeLimitExceeded,
    configured_timeout_s,
    time_limit,
)

pytest_plugins = ["pytester"]


def test_a_blocking_call_past_the_limit_raises_naming_what_was_running() -> None:
    began = time.monotonic()

    with pytest.raises(TimeLimitExceeded, match="sleeper") as excinfo, time_limit(0.5, "sleeper"):
        time.sleep(10)

    assert time.monotonic() - began < 5
    assert "0.5" in str(excinfo.value)


def test_a_call_inside_the_limit_is_left_alone() -> None:
    with time_limit(5, "quick"):
        time.sleep(0.05)


def test_the_alarm_is_cancelled_and_the_old_handler_restored_after_the_block() -> None:
    # The root conftest already runs this test under its own limit: that outer alarm must come
    # back, still counting down, and must not be replaced by the inner 5 seconds or by none.
    handler_before = signal.getsignal(signal.SIGALRM)
    outer_before = signal.getitimer(signal.ITIMER_REAL)[0]

    with time_limit(5, "quick"):
        pass

    assert signal.getsignal(signal.SIGALRM) == handler_before
    assert abs(signal.getitimer(signal.ITIMER_REAL)[0] - outer_before) < 1.0


def test_limits_nest_and_the_outer_one_keeps_running() -> None:
    with pytest.raises(TimeLimitExceeded, match="outer"), time_limit(1.5, "outer"):
        with time_limit(5, "inner"):
            time.sleep(0.1)
        time.sleep(10)


def test_zero_means_no_limit() -> None:
    outer = signal.getitimer(signal.ITIMER_REAL)[0]
    handler = signal.getsignal(signal.SIGALRM)

    with time_limit(0, "off"):
        assert signal.getsignal(signal.SIGALRM) == handler
        assert abs(signal.getitimer(signal.ITIMER_REAL)[0] - outer) < 1.0


def test_the_default_limit_is_five_minutes_and_the_environment_overrides_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DIUCS_TEST_TIMEOUT", raising=False)
    assert DEFAULT_TEST_TIMEOUT_S == 300.0
    assert configured_timeout_s() == 300.0

    monkeypatch.setenv("DIUCS_TEST_TIMEOUT", "42")
    assert configured_timeout_s() == 42.0
    monkeypatch.setenv("DIUCS_TEST_TIMEOUT", "0")
    assert configured_timeout_s() == 0.0
    monkeypatch.setenv("DIUCS_TEST_TIMEOUT", "not a number")
    assert configured_timeout_s() == 300.0


def test_the_conftest_fails_a_hanging_sync_test_and_a_hanging_async_test_and_runs_the_next(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DIUCS_TEST_TIMEOUT", "1")
    conftest_source = (Path(__file__).parents[2] / "conftest.py").read_text(encoding="utf-8")
    pytester.makeini(
        "[pytest]\nasyncio_mode = auto\nasyncio_default_fixture_loop_scope = session\n"
        "asyncio_default_test_loop_scope = session\nmarkers =\n    integration: needs docker\n"
    )
    pytester.mkdir("tests")
    (pytester.path / "tests" / "conftest.py").write_text(conftest_source, encoding="utf-8")
    pytester.makepyfile(
        **{
            "tests/test_hang": (
                "import asyncio, time\n"
                "def test_sync_hang():\n    time.sleep(20)\n"
                "async def test_async_hang():\n    await asyncio.sleep(20)\n"
                "async def test_fine_after_the_hangs():\n    await asyncio.sleep(0)\n"
            )
        }
    )
    began = time.monotonic()

    result = pytester.runpytest("-p", "no:cacheprovider")

    assert time.monotonic() - began < 30
    result.assert_outcomes(passed=1, failed=2)
    result.stdout.fnmatch_lines(["*TimeLimitExceeded*test_sync_hang*"])
    result.stdout.fnmatch_lines(["*TimeLimitExceeded*test_async_hang*"])
