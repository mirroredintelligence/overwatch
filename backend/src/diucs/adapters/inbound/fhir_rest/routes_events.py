"""Server-sent events stream for the live pages (R06). STUB for the red commit (DEC-010)."""

from typing import Final

from fastapi import APIRouter

KEEPALIVE_INTERVAL_SECONDS: Final[float] = 15.0
KEEPALIVE_LINE: Final = ": keep-alive\n\n"

router = APIRouter()


def to_sse(message: object) -> str | None:
    raise NotImplementedError


def parse_message(text: str) -> object | None:
    raise NotImplementedError
