"""Per-test time limit without a new dependency (F10b, DEC-135).

Lesson L67: a run stalled on its first Neo4j test for over nine minutes and nothing ended it. The
root conftest wraps each test's set-up (default 900 s, DIUCS_TEST_SETUP_TIMEOUT) and call phase
(default 300 s, DIUCS_TEST_TIMEOUT) in time_limit. Two stages:

1. Soft: a SIGALRM raises TimeLimitExceeded in the test, so that test fails with a message naming
   it and the stack where it was, and the next test still runs. It is a BaseException, so a broad
   `except Exception` in a library cannot swallow it and carry on waiting.
2. Hard: if the soft limit cannot stop the test (a call that never returns to Python, or a
   handler that is ignored), a timer thread, hard_grace_s() seconds later (default 60), releases
   pytest's output capture, writes the test's name and every thread's stack to the real stderr and
   ends the process with exit code 3. The harness lock is freed by the operating system, and the
   next session's reaper removes the container, because its owner is gone.

Set-up is where the first test waits for the harness lock and starts the container, and where an
image may be pulled. Those steps have their own bounds, so the harness wraps them in paused(), which
stops the clock of the innermost limit and gives it back what was left. Where SIGALRM does not exist
(Windows) or the caller is not the main thread, only the hard stage applies.
"""

import contextlib
import faulthandler
import os
import signal
import sys
import threading
import time
import traceback
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from types import FrameType

DEFAULT_TEST_TIMEOUT_S = 300.0
TIMEOUT_ENV = "DIUCS_TEST_TIMEOUT"
DEFAULT_SETUP_TIMEOUT_S = 900.0
SETUP_TIMEOUT_ENV = "DIUCS_TEST_SETUP_TIMEOUT"
HARD_GRACE_S = 60.0
GRACE_ENV = "DIUCS_TEST_HARD_GRACE"
HARD_EXIT_CODE = 3


class TimeLimitExceeded(BaseException):  # noqa: N818 - a BaseException on purpose, see the module
    """A test ran past its limit."""


def _seconds_from_environment(variable: str, default: float) -> float:
    try:
        value = float(os.environ.get(variable, ""))
    except ValueError:
        return default
    return value if value >= 0 else default


def configured_timeout_s() -> float:
    """The per-test limit in seconds: DIUCS_TEST_TIMEOUT, default 300. 0 turns the limit off. A
    value that is not a non-negative number is ignored."""
    return _seconds_from_environment(TIMEOUT_ENV, DEFAULT_TEST_TIMEOUT_S)


def setup_timeout_s() -> float:
    """The limit for a test's fixture set-up: DIUCS_TEST_SETUP_TIMEOUT, default 900. 0 turns it
    off. The harness's lock wait and image pull are paused, so they do not count."""
    return _seconds_from_environment(SETUP_TIMEOUT_ENV, DEFAULT_SETUP_TIMEOUT_S)


def hard_grace_s() -> float:
    """Seconds between the soft limit and the hard stage: DIUCS_TEST_HARD_GRACE, default 60."""
    value = _seconds_from_environment(GRACE_ENV, HARD_GRACE_S)
    return value if value > 0 else HARD_GRACE_S


@dataclass(eq=False)
class _Limit:
    seconds: float
    label: str
    release_capture: Callable[[], None] | None
    soft: bool
    deadline: float = 0.0
    hard: threading.Timer | None = field(default=None)


_active: list[_Limit] = []


def _message(label: str, seconds: float, frame: FrameType | None) -> str:
    where = "".join(traceback.format_stack(frame, limit=12)) if frame is not None else ""
    return (
        f"{label} ran longer than its {seconds:g} second limit ({TIMEOUT_ENV}, "
        f"{SETUP_TIMEOUT_ENV} for set-up). Where it was:\n{where}"
    )


def _hard_exit(limit: _Limit) -> None:  # pragma: no cover - ends the process
    """Release pytest's output capture (it has taken fd 2), then report to the real stderr and
    end the process. Without the release the report would be lost with the capture buffer."""
    if limit.release_capture is not None:
        with contextlib.suppress(Exception):
            limit.release_capture()
    stream = sys.__stderr__ or sys.stderr
    stream.write(
        f"\n{limit.label} did not stop {hard_grace_s():g} s after its {limit.seconds:g} s limit. "
        f"Ending the test process (exit code {HARD_EXIT_CODE}). Stacks of every thread follow.\n"
    )
    stream.flush()
    faulthandler.dump_traceback(file=stream, all_threads=True)
    stream.flush()
    os._exit(HARD_EXIT_CODE)


def _arm(limit: _Limit, remaining: float) -> None:
    limit.deadline = time.monotonic() + remaining
    if limit.soft:
        signal.setitimer(signal.ITIMER_REAL, remaining)
    limit.hard = threading.Timer(remaining + hard_grace_s(), _hard_exit, args=(limit,))
    limit.hard.daemon = True
    limit.hard.start()


def _disarm(limit: _Limit) -> None:
    if limit.hard is not None:
        limit.hard.cancel()
        limit.hard = None
    if limit.soft:
        signal.setitimer(signal.ITIMER_REAL, 0)


@contextmanager
def time_limit(
    seconds: float,
    label: str = "test",
    *,
    release_capture: Callable[[], None] | None = None,
) -> Iterator[None]:
    """Raise TimeLimitExceeded in the running code after `seconds`, and end the process if that
    does not stop it. 0 or less means no limit. `release_capture` gives the terminal back to the
    hard stage when pytest is capturing output."""
    if seconds <= 0:
        yield
        return
    soft = hasattr(signal, "SIGALRM") and threading.current_thread() is threading.main_thread()
    limit = _Limit(seconds, label, release_capture, soft)
    started = time.monotonic()
    previous_remaining = 0.0
    previous_handler = None
    if soft:

        def on_alarm(signum: int, frame: FrameType | None) -> None:
            raise TimeLimitExceeded(_message(label, seconds, frame))

        previous_remaining = signal.getitimer(signal.ITIMER_REAL)[0]
        previous_handler = signal.signal(signal.SIGALRM, on_alarm)
    _active.append(limit)
    _arm(limit, seconds)
    try:
        yield
    finally:
        _disarm(limit)
        _active.remove(limit)
        if soft:
            signal.signal(signal.SIGALRM, previous_handler)
            if previous_remaining > 0:
                left = previous_remaining - (time.monotonic() - started)
                signal.setitimer(signal.ITIMER_REAL, max(left, 0.001))


@contextmanager
def paused() -> Iterator[None]:
    """Stop the clock of the innermost running limit for the length of this block and give it back
    what was left, so a step with its own bound (the harness lock wait, an image pull) is not
    counted against a test's set-up. Does nothing when no limit is running."""
    if not _active:
        yield
        return
    limit = _active[-1]
    remaining = max(limit.deadline - time.monotonic(), 0.001)
    _disarm(limit)
    try:
        yield
    finally:
        _arm(limit, remaining)
