"""OpenTelemetry for the back end (O01). Stub for the red commit.

Nothing is exported and no span is created yet.
"""

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Any

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.trace import Tracer as OtelTracerApi

from diucs.bootstrap.settings import Settings

_EXPORTER_CLASS = OTLPSpanExporter


def build_provider(*, service_name: str, release: str, exporter: SpanExporter) -> TracerProvider:
    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(exporter))
    return provider


class AllowListSpanProcessor(SpanProcessor):
    def __init__(self, inner: SpanProcessor) -> None:
        self._inner = inner

    def on_start(self, span: Span, parent_context: Any = None) -> None:
        self._inner.on_start(span, parent_context)

    def on_end(self, span: ReadableSpan) -> None:
        self._inner.on_end(span)

    def shutdown(self) -> None:
        self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._inner.force_flush(timeout_millis)


class OtelTracer:
    def __init__(self, tracer: OtelTracerApi) -> None:
        self._tracer = tracer

    @contextmanager
    def span(self, name: str, attributes: Any) -> Iterator[Any]:
        yield None


def neo4j_span(
    query_id: str,
    access_mode: str,
    *,
    tracer: OtelTracerApi | None = None,
) -> AbstractContextManager[Any]:
    return _nothing()


@contextmanager
def _nothing() -> Iterator[None]:
    yield None


def record_query(
    query_id: str,
    access_mode: str,
    row_count: int,
    duration_ms: float,
    *,
    tracer: OtelTracerApi | None = None,
) -> None:
    return None


def _install_global_provider(provider: TracerProvider) -> None:
    return None


def configure_telemetry(settings: Settings) -> TracerProvider | None:
    return None
