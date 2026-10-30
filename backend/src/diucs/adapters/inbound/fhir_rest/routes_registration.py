"""Registration, scope list and the review of a registration over HTTP (R10). Stub: built in the
implement commit of R10."""

from fastapi import APIRouter
from fastapi.responses import Response

from diucs.domain.errors import DomainError

router = APIRouter(prefix="/fhir")


def refusal_outcome(error: DomainError) -> Response | None:
    raise NotImplementedError("R10: the business-rule refusal mapping is not built yet")


__all__ = ["refusal_outcome", "router"]
