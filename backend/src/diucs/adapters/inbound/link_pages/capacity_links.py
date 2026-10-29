"""The one-tap capacity link pages' API (L01): a stub for the red commit (DEC-010)."""

import logging
from dataclasses import dataclass
from typing import Any, Final

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

from diucs.application.ports.outbound.cache import Cache
from diucs.application.ports.outbound.sealing import ContentSealer
from diucs.application.use_cases.link_access import LinkAction

LINKS_PATH_PREFIX: Final = "/links"
LINK_PAGE_PATH: Final = ""
LINK_SCHEME: Final = ""
MAX_BODY_BYTES: Final = 0
SEND_THE_NUMBER_TEXT: Final = ""


class RedactLinkTokens(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return True


def install_log_redaction(logger_name: str = "uvicorn.access") -> None:
    return None


def _action_of(body: Any) -> LinkAction:
    return LinkAction(action="")


@dataclass(frozen=True, slots=True)
class LinkPagesDeps:
    cache: Cache
    sealer: ContentSealer


router = APIRouter(prefix=LINKS_PATH_PREFIX)


@router.get("/{token}")
async def view_link(token: str) -> Response:
    return JSONResponse({"state": "stub"}, status_code=501)


@router.post("/{token}")
async def respond_via_link(token: str) -> Response:
    return JSONResponse({"state": "stub"}, status_code=501)


@router.post("/{token}/renew")
async def renew_link(token: str) -> Response:
    return JSONResponse({"state": "stub"}, status_code=501)
