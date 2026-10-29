"""The consumer span for a bus message (O01). Stub for the red commit."""

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager

from diucs.application.ports.outbound.event_bus import BusMessage


def consumer_observer(tracer: object) -> object:
    @contextmanager
    def observe(message: BusMessage) -> Iterator[None]:
        yield None

    return observe
