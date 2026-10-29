"""Starts telemetry for a process (O01): the provider, the application tracer and the G01 query
observer. The serving and worker mains call start_telemetry once, before they serve, and
instrument_fastapi on their app when they serve HTTP. With no OTLP endpoint it does nothing."""

from opentelemetry.sdk.trace import TracerProvider

from diucs.adapters.outbound.graph_store.driver import set_query_observer
from diucs.adapters.outbound.telemetry import attributes as names
from diucs.adapters.outbound.telemetry.otel import (
    TelemetrySettings,
    configure_telemetry,
    query_observer,
)


def start_telemetry(settings: TelemetrySettings) -> TracerProvider | None:
    provider = configure_telemetry(settings)
    if provider is None:
        return None
    set_query_observer(query_observer(provider.get_tracer(names.INSTRUMENTATION_NAME)))
    return provider
