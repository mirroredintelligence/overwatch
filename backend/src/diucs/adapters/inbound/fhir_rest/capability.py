"""GET /fhir/metadata: the CapabilityStatement, and the registry later resource tasks add to (R01).

The statement is built with fhir.resources.R4B and dated from the container's clock, never from
the system clock (DEC-087 item 4).
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from fhir.resources.R4B.capabilitystatement import CapabilityStatement


FHIR_MEDIA_TYPE = "application/fhir+json; fhirVersion=4.3"
FHIR_VERSION = "4.3.0"

# The R4B TypeRestfulInteraction codes (DEC-087 item 5). A code outside this set is refused when
# the resource is registered, so a bad registration fails at start-up, not on each request.
INTERACTIONS = frozenset(
    {
        "read",
        "vread",
        "update",
        "patch",
        "delete",
        "history-instance",
        "history-type",
        "create",
        "search-type",
    }
)


class FhirJSONResponse(JSONResponse):
    media_type = FHIR_MEDIA_TYPE


# type -> (interactions, operations). Module-level, so the tests reset it with monkeypatch.
_RESOURCES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}

router = APIRouter()


def register_resource(
    resource_type: str, interactions: Sequence[str], operations: Sequence[str]
) -> None:
    """Advertise one resource type in the next /fhir/metadata.

    operations are canonical OperationDefinition URLs; the name is the last path segment. A type
    can be registered once. Refusals are ValueError, because they are programming errors.
    """
    if not resource_type:
        raise ValueError("a resource type is required")
    if any(code not in INTERACTIONS for code in interactions):
        raise ValueError(f"{resource_type}: an interaction code is not a FHIR R4B code")
    if resource_type in _RESOURCES:
        raise ValueError(f"{resource_type} is already registered")
    _RESOURCES[resource_type] = (tuple(interactions), tuple(operations))


def build_capability_statement(now: datetime) -> dict[str, Any]:
    resources: list[dict[str, Any]] = []
    for resource_type, (interactions, operations) in _RESOURCES.items():
        entry: dict[str, Any] = {
            "type": resource_type,
            "interaction": [{"code": code} for code in interactions],
        }
        if operations:
            entry["operation"] = [
                {"name": url.rsplit("/", 1)[-1], "definition": url} for url in operations
            ]
        resources.append(entry)
    statement = CapabilityStatement.model_validate(
        {
            "status": "active",
            "date": now.isoformat(),
            "kind": "instance",
            "fhirVersion": FHIR_VERSION,
            "format": ["application/fhir+json"],
            "rest": [{"mode": "server", "resource": resources}],
        }
    )
    body: dict[str, Any] = statement.model_dump(mode="json", by_alias=True, exclude_none=True)
    return body


@router.get("/metadata")
async def metadata(request: Request) -> FhirJSONResponse:
    # Read from app.state, not via app.py's get_container: app.py imports this module.
    return FhirJSONResponse(content=build_capability_statement(datetime.now(UTC)))
