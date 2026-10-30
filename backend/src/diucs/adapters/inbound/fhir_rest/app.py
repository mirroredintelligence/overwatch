"""The FastAPI application every FHIR route hangs off (R01).

The app reads only from the container it is given. It imports no outbound adapter and no bootstrap
module (the layers and independence contracts in backend/.importlinter). The process that serves
it calls container.startup() before serving and container.shutdown() on exit (DEC-012).
"""

import random
from collections.abc import Callable
from typing import Protocol, cast

from fastapi import APIRouter, FastAPI, Request

from diucs.adapters.inbound.fhir_rest import capability
from diucs.adapters.inbound.fhir_rest.errors import (
    BodyTypeMiddleware,
    UnhandledErrorMiddleware,
    install_exception_handlers,
)
from diucs.adapters.inbound.fhir_rest.routes_synthetic import SyntheticHook
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.geo import PostcodeLocator, TravelTime
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.tenants import TenantDirectory
from diucs.application.ports.outbound.terminology import FhirValidator, Terminology
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory


class ApiContainer(Protocol):
    """What the API reads from the composition root. Adapters may not import bootstrap (layers
    contract), so the container is typed by what it provides."""

    @property
    def clock(self) -> Clock: ...

    @property
    def uow_factory(self) -> UnitOfWorkFactory: ...

    @property
    def ids(self) -> IdGenerator: ...

    @property
    def tenants(self) -> TenantDirectory: ...

    @property
    def terminology(self) -> Terminology: ...

    @property
    def validator(self) -> FhirValidator: ...

    @property
    def postcodes(self) -> PostcodeLocator: ...

    @property
    def travel(self) -> TravelTime: ...

    @property
    def rng(self) -> random.Random: ...


def create_app(
    container: ApiContainer,
    synthetic: SyntheticHook | None = None,
    *,
    instrument: Callable[[FastAPI], None] | None = None,
) -> FastAPI:
    """Build the app. `synthetic` is the synthetic test hook (O09; None answers 404). `instrument`,
    when given, is called once with the finished app, so a process can add request tracing (the
    composition root decides, from the telemetry setting; the default adds nothing)."""
    # The OpenAPI pages are off: every response is FHIR, and the surface is the FHIR API only.
    app = FastAPI(
        title="DIUCS capacity FHIR API",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.container = container
    # The synthetic test hook (O09). None when it is not configured: the route then answers 404.
    app.state.synthetic = synthetic
    install_exception_handlers(app)
    # add_middleware wraps the app, so the last one added runs first: the catch-all is outermost.
    app.add_middleware(BodyTypeMiddleware)
    app.add_middleware(UnhandledErrorMiddleware)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    fhir = APIRouter(prefix="/fhir")
    fhir.include_router(capability.router)
    app.include_router(fhir)
    # Imported here: the route modules depend on auth, which imports this module (DEC-111).
    from diucs.adapters.inbound.fhir_rest import (
        routes_board,
        routes_cases,
        routes_criteria,
        routes_events,
        routes_identity,
        routes_lead,
        routes_public,
        routes_registration,
        routes_screens,
        routes_services,
        routes_terminology,
        routes_validate,
    )

    app.include_router(routes_events.router)
    # $board must be routed before any HealthcareService/{id} route, or {id} would take it.
    app.include_router(routes_board.router)
    app.include_router(routes_services.router)
    app.include_router(routes_cases.router)
    routes_services.register_capabilities()
    # The Pathways Dx lookup (R16) is not FHIR: a plain list for the score picker.
    app.include_router(routes_terminology.router)
    app.include_router(routes_validate.router)
    routes_validate.register_profiles()
    # Wall screen pairing (R15): JSON routes outside /fhir, over the U10 use cases.
    app.include_router(routes_screens.router)
    # Reporter identity: text code, PIN, the 30-day check and push subscriptions (R11).
    app.include_router(routes_identity.router)
    # The public tenant profile (TEN-040): no token, the tenant is the request host.
    app.include_router(routes_public.router)
    # Shift lead set-up and number changes (R08): FHIR operations over the U15 and U16 use cases.
    app.include_router(routes_lead.router)
    # Registration, scope list and criteria (R10): FHIR operations over the S6 use cases.
    app.include_router(routes_registration.router)
    app.include_router(routes_criteria.router)

    # Support codes and the support console (R18): JSON routes over the O06 and R18 use cases.
    from diucs.adapters.inbound.fhir_rest import routes_support

    app.include_router(routes_support.router)

    # The Twilio webhook (I07). It imports no FHIR module; the named ignore in .importlinter lets
    # this one module wire it in.
    from diucs.adapters.inbound.sms_webhook import routes as sms_routes

    app.include_router(sms_routes.router)

    # The one-tap capacity link pages (L01). Another inbound adapter, wired in the same way; the
    # named ignore in .importlinter lets this one module do it.
    from diucs.adapters.inbound.link_pages import capacity_links

    app.include_router(capacity_links.router)

    # The synthetic test hook (O09, TEN-G04): refuses everything unless it is configured and the
    # bearer is its token. Mounted always, so an unconfigured server answers the same 404.
    from diucs.adapters.inbound.fhir_rest import routes_synthetic

    app.include_router(routes_synthetic.router)
    if instrument is not None:
        instrument(app)
    return app


def get_container(request: Request) -> ApiContainer:
    return cast(ApiContainer, request.app.state.container)
