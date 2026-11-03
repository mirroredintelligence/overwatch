"""The postcode district routes for a service (DEC-1329), over HTTP.

GET  /postcode-districts/check?text=     200 {"prefix", "postcodes"}; 422 when the text is not a
                                        district with postcodes; 503 when the directory cannot
                                        answer, never a guessed count.
POST /postcode-districts/download?text=  202 {"prefix", "status": "queued"}: the confirmed district
                                        waits in the shared queue for a worker; nothing downloads
                                        here.

Only the shift lead (role lead) may use these. Every answer is no-store.
"""

from typing import Annotated, Final, Protocol, cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from overwatch.adapters.inbound.fhir_rest.app import get_container
from overwatch.adapters.inbound.fhir_rest.auth import require_role
from overwatch.adapters.inbound.fhir_rest.capability import FhirJSONResponse
from overwatch.adapters.inbound.fhir_rest.errors import TemporarilyUnavailable
from overwatch.application.actor import Actor
from overwatch.application.ports.outbound.clock import Clock
from overwatch.application.ports.outbound.lookups import LookupRejected, TransientLookupError
from overwatch.application.ports.outbound.postcode_directory import PostcodeDirectory
from overwatch.application.ports.outbound.postcode_download_queue import PostcodeDownloadQueue
from overwatch.application.use_cases.postcode_districts import CheckPostcodeDistrict
from overwatch.application.use_cases.postcode_download_queue import RequestPostcodeDownload
from overwatch.domain.codes import Role
from overwatch.domain.errors import ValidationFailed

router = APIRouter()

LEAD: Final = (Role.LEAD,)
RETRY_AFTER_DIRECTORY_SECONDS: Final = 30
NO_STORE: Final = {"Cache-Control": "no-store"}


class _Container(Protocol):
    @property
    def postcode_directory(self) -> PostcodeDirectory: ...

    @property
    def postcode_queue(self) -> PostcodeDownloadQueue: ...

    @property
    def clock(self) -> Clock: ...


@router.get("/postcode-districts/check")
async def check_postcode_district(
    request: Request, actor: Annotated[Actor, Depends(require_role(*LEAD))]
) -> Response:
    text = request.query_params.get("text", "")
    container = cast(_Container, get_container(request))
    try:
        check = await CheckPostcodeDistrict(container.postcode_directory)(text)
    except TransientLookupError, LookupRejected:
        # A check that could not answer is never reported as "not found" (fail closed).
        raise TemporarilyUnavailable(RETRY_AFTER_DIRECTORY_SECONDS) from None
    if check is None:
        raise ValidationFailed("district", "Enter a postcode district that has postcodes")
    return FhirJSONResponse(
        content={"prefix": check.prefix, "postcodes": check.postcodes}, headers=NO_STORE
    )


@router.post("/postcode-districts/download", status_code=202)
async def request_postcode_download(
    request: Request, actor: Annotated[Actor, Depends(require_role(*LEAD))]
) -> Response:
    text = request.query_params.get("text", "")
    container = cast(_Container, get_container(request))
    try:
        prefix = await RequestPostcodeDownload(container.postcode_queue)(
            text, container.clock.now()
        )
    except ValueError:
        raise ValidationFailed("district", "Enter a postcode district") from None
    return FhirJSONResponse(
        content={"prefix": prefix, "status": "queued"}, status_code=202, headers=NO_STORE
    )
