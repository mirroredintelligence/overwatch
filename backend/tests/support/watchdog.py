"""Per-test time limit without a new dependency (F10b, DEC-135).

Lesson L67: a run stalled on its first Neo4j test for over nine minutes and nothing ended it. The
root conftest wraps each test's call phase in time_limit(configured_timeout_s()). Two stages:

1. Soft: a SIGALRM raises TimeLimitExceeded in the test, so that test fails with a message naming
   it and the stack where it was, and the next test still runs. It is a BaseException, so a broad
   `except Exception` in a library cannot swallow it and carry on waiting.
2. Hard: if the soft limit cannot stop the test (a call that never returns to Python, or a
   handler that is ignored), a timer thread dumps every thread's stack and ends the process
   HARD_GRACE_S seconds later. The harness lock is freed by the operating system, and the next
   session's reaper removes the container, because its owner is gone.

The limit covers the call phase only. Fixture set-up, where the first test waits for the harness
lock and starts the container, has its own bounds (DIUCS_NEO4J_LOCK_TIMEOUT and
DIUCS_NEO4J_READY_TIMEOUT). Where SIGALRM does not exist (Windows) or the caller is not the main
thread, only the hard stage applies.
"""

import faulthandler
import os
import signal
import sys
import threading
import time
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from types import FrameType

DEFAULT_TEST_TIMEOUT_S = 300.0
TIMEOUT_ENV = "DIUCS_TEST_TIMEOUT"
HARD_GRACE_S = 60.0
HARD_EXIT_CODE = 3


class TimeLimitExceeded(BaseException):  # noqa: N818 - a BaseException on purpose, see the module
    """A test ran past its limit."""


def configured_timeout_s() -> float:
    """The per-test limit in seconds: DIUCS_TEST_TIMEOUT, default 300. 0 turns the limit off. A
    value that is not a non-negative number is ignored."""
    try:
        value = float(os.environ.get(TIMEOUT_ENV, ""))
    except ValueError:
        return DEFAULT_TEST_TIMEOUT_S
    return value if value >= 0 else DEFAULT_TEST_TIMEOUT_S


def _message(label: str, seconds: float, frame: FrameType | None) -> str:
    where = "".join(traceback.format_stack(frame, limit=12)) if frame is not None else ""
    return (
        f"{label} ran longer than its {seconds:g} second limit ({TIMEOUT_ENV}). "
        f"Where it was:\n{where}"
    )


def _hard_exit(label: str, seconds: float) -> None:  # pragma: no cover - ends the process
    sys.stderr.write(
        f"\n{label} did not stop {HARD_GRACE_S:g} s after its {seconds:g} s limit. "
        f"Ending the test process. Stacks of every thread follow.\n"
    )
    faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
    sys.stderr.flush()
    os._exit(HARD_EXIT_CODE)


@contextmanager
def time_limit(seconds: float, label: str = "test") -> Iterator[None]:
    """Raise TimeLimitExceeded in the running code after `seconds`. 0 or less means no limit."""
    if seconds <= 0:
        yield
        return
    hard = threading.Timer(seconds + HARD_GRACE_S, _hard_exit, args=(label, seconds))
    hard.daemon = True
    soft = hasattr(signal, "SIGALRM") and threading.current_thread() is threading.main_thread()
    started = time.monotonic()
    previous_remaining = 0.0
    previous_handler = None
    if soft:

        def on_alarm(signum: int, frame: FrameType | None) -> None:
            raise TimeLimitExceeded(_message(label, seconds, frame))

        previous_remaining = signal.getitimer(signal.ITIMER_REAL)[0]
        previous_handler = signal.signal(signal.SIGALRM, on_alarm)
        signal.setitimer(signal.ITIMER_REAL, seconds)
    hard.start()
    try:
        yield
    finally:
        hard.cancel()
        if soft:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_handler)
            if previous_remaining > 0:
                left = previous_remaining - (time.monotonic() - started)
                signal.setitimer(signal.ITIMER_REAL, max(left, 0.001))
