"""GET /terminology/pathways-dx: search the Pathways Dx codes (R16). DEC-010 red stub."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/terminology/pathways-dx")
async def search_pathways_dx() -> list[dict[str, str]]:
    return []
