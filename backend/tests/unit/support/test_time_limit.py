"""A per-test time limit that needs no new dependency (F10b, DEC-135).

Lesson L67: a run stalled on its first Neo4j test for over nine minutes and nothing ended it. The
limit is a SIGALRM watchdog in the root conftest, built on tests/support/watchdog.py. A test that
hangs fails with a message that names it and shows where it was; the next test still runs.
"""

import contextlib
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from tests.support import neo4j as harness
from tests.support.watchdog import (
    DEFAULT_TEST_TIMEOUT_S,
    TimeLimitExceeded,
    configured_timeout_s,
    hard_grace_s,
    paused,
    setup_timeout_s,
    time_limit,
)

BACKEND = Path(__file__).resolve().parents[3]

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


# ---- verifier follow-ups: B2c, B2d, N2, N3 ------------------------------------------------------


def _run_script(script: str, **env: str) -> tuple[subprocess.CompletedProcess[str], float]:
    began = time.monotonic()
    try:
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=BACKEND,
            env={**os.environ, "PYTHONPATH": str(BACKEND), **env},
            capture_output=True,
            text=True,
            timeout=40,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("the child process was not ended by the time limit")
    return result, time.monotonic() - began


HUNG = """
import io, signal, sys, time
from tests.support.watchdog import time_limit
with time_limit(1, "tests/test_x.py::test_stuck"):
    signal.signal(signal.SIGALRM, signal.SIG_IGN)  # the soft stage cannot stop this test
    sys.stderr = io.StringIO()  # what pytest's output capture does to sys.stderr
    time.sleep(60)
print("not reached")
"""


def test_the_hard_stage_ends_a_stuck_test_and_its_report_reaches_the_real_stderr() -> None:
    result, took = _run_script(HUNG, DIUCS_TEST_HARD_GRACE="1")

    assert result.returncode == 3
    assert took < 20  # limit 1 s plus grace 1 s, not the 60 s default grace
    assert "not reached" not in result.stdout
    # sys.stderr was replaced by a capture buffer; the report must still reach the real stderr
    assert "tests/test_x.py::test_stuck" in result.stderr
    assert "did not stop" in result.stderr
    assert "most recent call first" in result.stderr  # the stack of every thread


def test_the_hard_grace_defaults_to_sixty_seconds_and_the_environment_overrides_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DIUCS_TEST_HARD_GRACE", raising=False)
    assert hard_grace_s() == 60.0
    monkeypatch.setenv("DIUCS_TEST_HARD_GRACE", "2.5")
    assert hard_grace_s() == 2.5
    monkeypatch.setenv("DIUCS_TEST_HARD_GRACE", "nonsense")
    assert hard_grace_s() == 60.0
    monkeypatch.setenv("DIUCS_TEST_HARD_GRACE", "-1")
    assert hard_grace_s() == 60.0


CLEAN = """
import signal
from tests.support.watchdog import time_limit
before = signal.getsignal(signal.SIGALRM)
with time_limit(5, "x"):
    assert 0 < signal.getitimer(signal.ITIMER_REAL)[0] <= 5
assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0), signal.getitimer(signal.ITIMER_REAL)
assert signal.getsignal(signal.SIGALRM) == before
print("clean")
"""


def test_with_no_outer_alarm_the_block_leaves_no_alarm_and_the_old_handler() -> None:
    # In this test process the root conftest's own alarm masks the same check, so it runs alone.
    result, _ = _run_script(CLEAN)

    assert result.returncode == 0, result.stderr
    assert "clean" in result.stdout


def test_the_setup_limit_defaults_to_fifteen_minutes_and_the_environment_overrides_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DIUCS_TEST_SETUP_TIMEOUT", raising=False)
    assert setup_timeout_s() == 900.0
    monkeypatch.setenv("DIUCS_TEST_SETUP_TIMEOUT", "30")
    assert setup_timeout_s() == 30.0
    monkeypatch.setenv("DIUCS_TEST_SETUP_TIMEOUT", "0")
    assert setup_timeout_s() == 0.0
    monkeypatch.setenv("DIUCS_TEST_SETUP_TIMEOUT", "nonsense")
    assert setup_timeout_s() == 900.0


def test_a_paused_limit_does_not_count_the_paused_time_and_counts_the_rest() -> None:
    began = time.monotonic()

    with pytest.raises(TimeLimitExceeded, match="paused-limit"), time_limit(1.5, "paused-limit"):
        time.sleep(1.0)  # 0.5 s of the limit is left
        with paused():
            time.sleep(1.5)  # longer than what was left, but not counted
        time.sleep(10)

    # 1.0 + 1.5 + the 0.5 s that was left. Giving back the full 1.5 s would end near 4.0.
    assert 2.9 <= time.monotonic() - began <= 3.7


def test_a_broad_except_exception_cannot_swallow_the_limit() -> None:
    with pytest.raises(TimeLimitExceeded), time_limit(0.5, "swallowed"):
        with contextlib.suppress(Exception):  # what a library's retry loop might do
            time.sleep(5)
        time.sleep(5)  # only reached if the limit was swallowed


def test_pausing_with_no_limit_running_does_nothing() -> None:
    with paused():
        pass


def test_the_lock_wait_of_a_start_is_not_counted_against_the_setup_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import fcntl
    import subprocess as sp

    path = tmp_path / "harness.lock"
    monkeypatch.setenv("DIUCS_NEO4J_LOCK", str(path))
    other = os.open(path, os.O_RDWR | os.O_CREAT, 0o666)
    fcntl.flock(other, fcntl.LOCK_EX)
    threading.Timer(2.5, lambda: os.close(other)).start()  # frees the lock after 2.5 s

    def docker(*args: str, timeout: float = 60.0) -> sp.CompletedProcess[str]:
        return sp.CompletedProcess(args=list(args), returncode=0, stdout="", stderr="")

    with time_limit(1.0, "set-up of the first test"):
        container = harness.start_throwaway_neo4j(run=docker, probe=lambda c: True)

    harness.stop_throwaway_neo4j(container, run=docker)


def test_a_slow_image_pull_is_not_counted_against_the_setup_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import subprocess as sp

    monkeypatch.setenv("DIUCS_NEO4J_LOCK", str(tmp_path / "harness.lock"))

    def docker(*args: str, timeout: float = 60.0) -> sp.CompletedProcess[str]:
        if args[:2] == ("image", "inspect"):
            return sp.CompletedProcess(args=list(args), returncode=1, stdout="", stderr="")
        if args[0] == "pull":
            time.sleep(2.5)
        return sp.CompletedProcess(args=list(args), returncode=0, stdout="", stderr="")

    with time_limit(1.0, "set-up of the first test"):
        container = harness.start_throwaway_neo4j(run=docker, probe=lambda c: True)

    harness.stop_throwaway_neo4j(container, run=docker)


def _setup_session(pytester: pytest.Pytester, body: str) -> pytest.RunResult:
    conftest_source = (Path(__file__).parents[2] / "conftest.py").read_text(encoding="utf-8")
    pytester.makeini(
        "[pytest]\nasyncio_mode = auto\nasyncio_default_fixture_loop_scope = session\n"
        "asyncio_default_test_loop_scope = session\nmarkers =\n    integration: needs docker\n"
    )
    pytester.mkdir("tests")
    (pytester.path / "tests" / "conftest.py").write_text(conftest_source, encoding="utf-8")
    pytester.makepyfile(**{"tests/test_setup": body})
    return pytester.runpytest("-p", "no:cacheprovider")


SLOW_SETUP = (
    "import time, pytest\n"
    "@pytest.fixture\n"
    "def slow():\n    time.sleep(20)\n"
    "def test_needs_it(slow):\n    pass\n"
    "def test_does_not(): pass\n"
)


def test_the_conftest_fails_a_test_whose_set_up_hangs_and_runs_the_next(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DIUCS_TEST_SETUP_TIMEOUT", "1")
    began = time.monotonic()

    result = _setup_session(pytester, SLOW_SETUP)

    assert time.monotonic() - began < 30
    result.assert_outcomes(passed=1, errors=1)
    result.stdout.fnmatch_lines(["*TimeLimitExceeded*test_needs_it*set-up*"])


def test_a_set_up_limit_of_zero_turns_it_off(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DIUCS_TEST_SETUP_TIMEOUT", "0")

    result = _setup_session(pytester, SLOW_SETUP.replace("sleep(20)", "sleep(2)"))

    result.assert_outcomes(passed=2)


def test_under_pytests_default_output_capture_the_hard_report_still_reaches_the_terminal(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The verifier's N2: with fd capture on (the default), the report written at the hard stage
    # was lost with the capture buffer and the run just ended with exit code 3.
    monkeypatch.setenv("DIUCS_TEST_TIMEOUT", "1")
    monkeypatch.setenv("DIUCS_TEST_HARD_GRACE", "1")
    monkeypatch.setenv("PYTHONPATH", str(BACKEND))
    conftest_source = (Path(__file__).parents[2] / "conftest.py").read_text(encoding="utf-8")
    pytester.makeini("[pytest]\nmarkers =\n    integration: needs docker\n")
    pytester.mkdir("tests")
    (pytester.path / "tests" / "conftest.py").write_text(conftest_source, encoding="utf-8")
    pytester.makepyfile(
        **{
            "tests/test_stuck": (
                "import signal, time\n"
                "def test_stuck():\n"
                "    signal.signal(signal.SIGALRM, signal.SIG_IGN)\n"
                "    time.sleep(60)\n"
            )
        }
    )

    result = pytester.runpytest_subprocess("-p", "no:cacheprovider")

    assert result.ret == 3
    output = result.stdout.str() + result.stderr.str()
    assert "test_stuck" in output
    assert "did not stop" in output
    assert "most recent call first" in output
