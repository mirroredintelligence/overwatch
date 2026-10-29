"""Tracing seam for the application layer (O01). The application imports no OpenTelemetry.

Stub for the red commit: no span is produced yet.
"""

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager, nullcontext
from typing import Any, Protocol

AttrValue = str | bool | int | float


class Span(Protocol):
    def set_attribute(self, key: str, value: AttrValue) -> None: ...

    def fail(self, error_type: str) -> None: ...


class _NoopSpan:
    def set_attribute(self, key: str, value: AttrValue) -> None:
        return None

    def fail(self, error_type: str) -> None:
        return None


class Tracer(Protocol):
    def span(
        self, name: str, attributes: Mapping[str, AttrValue]
    ) -> AbstractContextManager[Span]: ...


class NoopTracer:
    def span(self, name: str, attributes: Mapping[str, AttrValue]) -> AbstractContextManager[Span]:
        return nullcontext(_NoopSpan())


_tracer: Tracer = NoopTracer()


def set_tracer(tracer: Tracer) -> None:
    global _tracer
    _tracer = tracer


def get_tracer() -> Tracer:
    return _tracer


def annotate_usecase(key: str, value: AttrValue) -> None:
    return None


def traced_use_case(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        return fn

    return decorate
