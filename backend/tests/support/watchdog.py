"""Per-test time limit (F10b). Stub: no behaviour yet (DEC-010)."""

from collections.abc import Iterator
from contextlib import contextmanager

DEFAULT_TEST_TIMEOUT_S = 300.0
TIMEOUT_ENV = "DIUCS_TEST_TIMEOUT"


class TimeLimitExceeded(Exception):
    """A test ran past its limit."""


def configured_timeout_s() -> float:
    return 0.0


@contextmanager
def time_limit(seconds: float, label: str = "test") -> Iterator[None]:
    yield
