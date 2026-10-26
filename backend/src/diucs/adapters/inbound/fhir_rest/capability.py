"""GET /fhir/metadata: the CapabilityStatement, and the registry later resource tasks add to (R01).

Stub for the red commit (DEC-010). FhirJSONResponse is only configuration, so it is real.
"""

from collections.abc import Sequence

from fastapi import APIRouter
from fastapi.responses import JSONResponse

FHIR_MEDIA_TYPE = "application/fhir+json; fhirVersion=4.3"


class FhirJSONResponse(JSONResponse):
    media_type = FHIR_MEDIA_TYPE


# type -> (interactions, operations). Module-level, so the tests reset it with monkeypatch.
_RESOURCES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}

router = APIRouter()


def register_resource(
    resource_type: str, interactions: Sequence[str], operations: Sequence[str]
) -> None:
    raise NotImplementedError("R01: register_resource is not built yet")
