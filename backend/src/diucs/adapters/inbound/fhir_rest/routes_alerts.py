"""Alert subscriptions, alert acknowledgement and the week summary over HTTP (R12). Stub: built in
the implement commit of R12."""

from fastapi import APIRouter

router = APIRouter(prefix="/fhir")

__all__ = ["router"]
