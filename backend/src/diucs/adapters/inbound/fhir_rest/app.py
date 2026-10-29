"""The FastAPI application every FHIR route hangs off (R01).

The app reads only from the container it is given. It imports no outbound adapter and no bootstrap
module (the layers and independence contracts in backend/.importlinter). The process that serves
it calls container.startup() before serving and container.shutdown() on exit (DEC-012).
"""

from typing import Protocol, cast

from fastapi import APIRouter, FastAPI, Request

from diucs.adapters.inbound.fhir_rest import capability
from diucs.adapters.inbound.fhir_rest.errors import (
    BodyTypeMiddleware,
    UnhandledErrorMiddleware,
    install_exception_handlers,
)
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
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


def create_app(container: ApiContainer) -> FastAPI:
    # The OpenAPI pages are off: every response is FHIR, and the surface is the FHIR API only.
    app = FastAPI(
        title="DIUCS capacity FHIR API",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.container = container
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
    from diucs.adapters.inbound.fhir_rest import routes_board, routes_events

    app.include_router(routes_events.router)
    # $board must be routed before any HealthcareService/{id} route, or {id} would take it.
    app.include_router(routes_board.router)

    # The Twilio webhook (I07). It imports no FHIR module; the named ignore in .importlinter lets
    # this one module wire it in.
    from diucs.adapters.inbound.sms_webhook import routes as sms_routes

    app.include_router(sms_routes.router)
    return app


def get_container(request: Request) -> ApiContainer:
    return cast(ApiContainer, request.app.state.container)
