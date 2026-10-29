"""The application's tracing seam (O01). The application layer imports no OpenTelemetry: the
adapter supplies a Tracer, and until one is set every span is a no-op.

Every use case is one span named `usecase.{Name}`, with `usecase.outcome` set to `ok` or to the
class name of the exception it raised. The span records the class name only, never the message,
because a domain error can carry data. A use case adds its own `usecase.*` attributes through
`annotate_usecase`, which is a no-op outside a use case span.
"""

import functools
from collections.abc import Awaitable, Callable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar
from typing import ParamSpec, Protocol, TypeVar

AttrValue = str | bool | int | float

USECASE_OUTCOME: str = "usecase.outcome"
USECASE_NAMESPACE: str = "usecase."

P = ParamSpec("P")
R = TypeVar("R")


class Span(Protocol):
    def set_attribute(self, key: str, value: AttrValue) -> None: ...

    def fail(self, error_type: str) -> None: ...


class Tracer(Protocol):
    def span(
        self, name: str, attributes: Mapping[str, AttrValue]
    ) -> AbstractContextManager[Span]: ...


class _NoopSpan:
    def set_attribute(self, key: str, value: AttrValue) -> None:
        return None

    def fail(self, error_type: str) -> None:
        return None


class NoopTracer:
    @contextmanager
    def span(self, name: str, attributes: Mapping[str, AttrValue]) -> Iterator[Span]:
        yield _NoopSpan()


_tracer: Tracer = NoopTracer()
_current_usecase: ContextVar[Span | None] = ContextVar("current_usecase_span", default=None)


def set_tracer(tracer: Tracer) -> None:
    global _tracer
    _tracer = tracer


def get_tracer() -> Tracer:
    return _tracer


def annotate_usecase(key: str, value: AttrValue) -> None:
    """Set one attribute on the use case span that is running in this context. Refuses a key
    outside the `usecase.` namespace; does nothing when no use case span is running."""
    if not key.startswith(USECASE_NAMESPACE):
        raise ValueError("use case annotations must use the usecase. namespace")
    span = _current_usecase.get()
    if span is not None:
        span.set_attribute(key, value)


def traced_use_case(name: str) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Decorate an async `execute` so each call is one span named `usecase.{name}`."""
    span_name = f"usecase.{name}"

    def decorate(fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @functools.wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            with _tracer.span(span_name, {}) as span:
                token = _current_usecase.set(span)
                try:
                    result = await fn(*args, **kwargs)
                except BaseException as error:
                    outcome = type(error).__name__
                    span.set_attribute(USECASE_OUTCOME, outcome)
                    span.fail(outcome)
                    raise
                finally:
                    _current_usecase.reset(token)
                span.set_attribute(USECASE_OUTCOME, "ok")
                return result

        return wrapper

    return decorate
