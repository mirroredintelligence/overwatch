"""The synthetic test hook (O09): POST /test/synthetic/prompt. Stub: the tests are written first."""

from dataclasses import dataclass
from typing import Protocol

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/test/synthetic")


class SyntheticLinkIssuer(Protocol):
    async def issue(self) -> str:
        """Issue a fresh capacity link for the synthetic test service; return the link."""
        ...


@dataclass(frozen=True, slots=True)
class SyntheticHook:
    enabled: bool
    token: str | None
    tenant_id: str
    issuer: SyntheticLinkIssuer

    def admits(self, authorization: str | None) -> bool:
        raise NotImplementedError


@router.post("/prompt", status_code=201)
async def post_prompt(request: Request) -> JSONResponse:
    raise NotImplementedError
