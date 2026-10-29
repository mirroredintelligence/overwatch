"""OpenTelemetry for the back end (O01): the tracer provider, the allow-list span processor, the
application's tracer, the named-query span and the FastAPI instrumentation.

Nothing here runs unless configure_telemetry is given an OTLP endpoint. With no endpoint it installs
no exporter and no tracer, and returns None, so the application runs with its no-op tracer.
Adapters import no bootstrap module (layers contract), so the settings are typed by the two fields
this module reads.
"""

import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any, Final, Protocol

from opentelemetry import trace as otel_trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import Event, ReadableSpan, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.trace import Status, StatusCode

from diucs.adapters.outbound.telemetry import attributes as names
from diucs.adapters.outbound.telemetry.redaction import (
    clean_attributes,
    install_log_redaction,
    redact_text,
)
from diucs.application import tracing

_NANOSECONDS_PER_MILLISECOND: Final = 1_000_000


class TelemetrySettings(Protocol):
    """The two settings this module reads. Settings satisfies it."""

    @property
    def otlp_endpoint(self) -> str: ...

    @property
    def release(self) -> str: ...


def _install_global_provider(provider: TracerProvider) -> None:
    otel_trace.set_tracer_provider(provider)


def _allow_listed_event(event: Event) -> Event:
    return Event(
        event.name,
        clean_attributes(event.attributes or {}),
        event.timestamp,
    )


def _allow_listed(span: ReadableSpan) -> ReadableSpan:
    """A copy of the span with its attributes, event attributes and error text filtered. The copy
    is a real ReadableSpan, so every exporter, including to_json, sees the filtered values."""
    status = span.status
    if status.status_code == StatusCode.ERROR and status.description:
        status = Status(StatusCode.ERROR, redact_text(status.description))
    return ReadableSpan(
        name=span.name,
        context=span.context,
        parent=span.parent,
        resource=span.resource,
        attributes=clean_attributes(span.attributes or {}),
        events=tuple(_allow_listed_event(event) for event in span.events),
        links=span.links,
        kind=span.kind,
        status=status,
        start_time=span.start_time,
        end_time=span.end_time,
        instrumentation_scope=span.instrumentation_scope,
    )


class AllowListSpanProcessor(SpanProcessor):
    """Removes every attribute that is not on the allow-list before the inner processor (and so
    the exporter) sees the span."""

    def __init__(self, inner: SpanProcessor) -> None:
        self._inner = inner

    def on_start(self, span: Any, parent_context: Any = None) -> None:
        self._inner.on_start(span, parent_context)

    def on_end(self, span: ReadableSpan) -> None:
        self._inner.on_end(_allow_listed(span))

    def shutdown(self) -> None:
        self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._inner.force_flush(timeout_millis)


class _OtelSpan:
    def __init__(self, span: otel_trace.Span) -> None:
        self._span = span

    def set_attribute(self, key: str, value: tracing.AttrValue) -> None:
        self._span.set_attribute(key, value)

    def fail(self, error_type: str) -> None:
        # The class name only: an exception message can carry data (lesson L111).
        self._span.set_status(Status(StatusCode.ERROR, error_type))
        self._span.set_attribute(names.ERROR_TYPE, error_type)


class OtelTracer:
    """The application's Tracer, backed by an OpenTelemetry tracer."""

    def __init__(self, tracer: otel_trace.Tracer) -> None:
        self._tracer = tracer

    def current_span(self) -> _OtelSpan:
        """The span OpenTelemetry's own context holds as current. A span that is not recording (none
        open) takes attributes and does nothing, so an annotation outside a span is harmless."""
        return _OtelSpan(otel_trace.get_current_span())

    @contextmanager
    def span(self, name: str, attributes: Mapping[str, tracing.AttrValue]) -> Iterator[_OtelSpan]:
        with self._tracer.start_as_current_span(
            name,
            attributes=dict(attributes),
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            yield _OtelSpan(span)


def _neo4j_attributes(query_id: str, access_mode: str) -> dict[str, str]:
    return {
        names.DB_SYSTEM: names.NEO4J_SYSTEM,
        names.DB_SYSTEM_NAME: names.NEO4J_SYSTEM,
        names.DB_QUERY_ID: query_id,
        names.DB_ACCESS_MODE: access_mode,
    }


@contextmanager
def neo4j_span(
    query_id: str,
    access_mode: str,
    *,
    tracer: otel_trace.Tracer | None = None,
) -> Iterator[otel_trace.Span]:
    """A span for one named query. It carries the query id and the access mode, never the Cypher."""
    active = otel_trace.get_tracer(names.INSTRUMENTATION_NAME) if tracer is None else tracer
    with active.start_as_current_span(
        names.SPAN_NEO4J_QUERY.format(query_id=query_id),
        attributes=_neo4j_attributes(query_id, access_mode),
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        yield span


def record_query(
    query_id: str,
    access_mode: str,
    row_count: int,
    duration_ms: float,
    *,
    tracer: otel_trace.Tracer | None = None,
) -> None:
    """The G01 query observer: a finished neo4j span for a query that has already run. The query
    ran before the observer is called, so the span is placed back in time by its duration."""
    active = otel_trace.get_tracer(names.INSTRUMENTATION_NAME) if tracer is None else tracer
    end_ns = time.time_ns()
    start_ns = end_ns - round(duration_ms * _NANOSECONDS_PER_MILLISECOND)
    span = active.start_span(
        names.SPAN_NEO4J_QUERY.format(query_id=query_id),
        attributes=_neo4j_attributes(query_id, access_mode),
        start_time=start_ns,
    )
    span.set_attribute(names.DB_ROW_COUNT, row_count)
    span.end(end_time=end_ns)


def query_observer(
    tracer: otel_trace.Tracer,
) -> Callable[[str, str, int, float], None]:
    """The function the composition root gives set_query_observer (G01)."""

    def observe(query_id: str, access_mode: str, row_count: int, duration_ms: float) -> None:
        record_query(query_id, access_mode, row_count, duration_ms, tracer=tracer)

    return observe


def build_provider(*, service_name: str, release: str, exporter: SpanExporter) -> TracerProvider:
    provider = TracerProvider(
        resource=Resource.create({"service.name": service_name, "service.version": release}),
    )
    provider.add_span_processor(AllowListSpanProcessor(BatchSpanProcessor(exporter)))
    return provider


def configure_telemetry(settings: TelemetrySettings) -> TracerProvider | None:
    """Install the exporter, the global provider and the application tracer, when an endpoint is
    set. With no endpoint nothing is installed and None is returned. Log redaction is installed
    either way, so a process without telemetry still scrubs its logs."""
    install_log_redaction()
    if not settings.otlp_endpoint:
        return None
    exporter = OTLPSpanExporter(endpoint=settings.otlp_endpoint)
    provider = build_provider(
        service_name=names.SERVICE_NAME,
        release=settings.release,
        exporter=exporter,
    )
    _install_global_provider(provider)
    tracing.set_tracer(OtelTracer(provider.get_tracer(names.INSTRUMENTATION_NAME)))
    return provider


_INSTRUMENTED_FLAG: Final = "diucs_fastapi_instrumented"


def instrument_fastapi(app: Any, provider: TracerProvider | None = None) -> None:
    """Span every FastAPI request under its route template (http.route), never its raw URL. The
    raw URL and the body are not on the allow-list, so they are removed before export. A None
    provider means the global one. Once an app is instrumented, a second call does nothing: a
    request gets one server span, not two."""
    if getattr(app.state, _INSTRUMENTED_FLAG, False):
        return
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=provider,
        excluded_urls="health",
        exclude_spans=["receive", "send"],  # one server span per request, not three
    )
    setattr(app.state, _INSTRUMENTED_FLAG, True)
