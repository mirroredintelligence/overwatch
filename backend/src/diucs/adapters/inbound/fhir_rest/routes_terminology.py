"""GET /terminology/pathways-dx: search the Pathways Dx codes for the score picker (R16).

Roles advisor and clinical only. Any other role gets the same 404 as a missing record, and the role
check runs before the text is read, so a reporter gets 404 even for short text. The text is trimmed
and must be at least MIN_SEARCH_LENGTH characters, else 400 invalid. The answer is a plain JSON list
of {code, display}, at most 20, in code order. The codes come from the Terminology port, so the
source is a configuration change. The route reads no tenant record and opens no unit of work.
"""

from typing import Annotated, Final

from fastapi import APIRouter, Depends, Request

from diucs.adapters.inbound.fhir_rest.app import get_container
from diucs.adapters.inbound.fhir_rest.auth import require_role
from diucs.application.actor import Actor
from diucs.domain.codes import Role
from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.code_search import MIN_SEARCH_LENGTH

router = APIRouter()

RESULT_LIMIT: Final = 20
TOO_SHORT: Final = f"Type at least {MIN_SEARCH_LENGTH} characters"


@router.get("/terminology/pathways-dx")
async def search_pathways_dx(
    request: Request,
    q: str,
    _actor: Annotated[Actor, Depends(require_role(Role.ADVISOR, Role.CLINICAL))],
) -> list[dict[str, str]]:
    text = q.strip()
    if len(text) < MIN_SEARCH_LENGTH:
        raise ValidationFailed("q", TOO_SHORT)
    found = await get_container(request).terminology.search_pathways_dx(text, RESULT_LIMIT)
    return [{"code": code, "display": display} for code, display in found]
