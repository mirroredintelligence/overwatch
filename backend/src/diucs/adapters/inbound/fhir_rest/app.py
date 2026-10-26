"""The FastAPI application every FHIR route hangs off (R01).

Stub for the red commit (DEC-010): the signatures are final, the bodies are not built yet.
"""

from typing import Protocol

from fastapi import FastAPI, Request

from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory


class ApiContainer(Protocol):
    """What the API reads from the composition root. Adapters may not import bootstrap (layers
    contract), so the container is typed by what it provides."""

    @property
    def clock(self) -> Clock: ...

    @property
    def uow_factory(self) -> UnitOfWorkFactory: ...


def create_app(container: ApiContainer) -> FastAPI:
    raise NotImplementedError("R01: create_app is not built yet")


def get_container(request: Request) -> ApiContainer:
    raise NotImplementedError("R01: get_container is not built yet")
