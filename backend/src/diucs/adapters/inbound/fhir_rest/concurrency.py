"""ETag, If-Match and Idempotency-Key handling for the FHIR API (R03).

RED STUB (DEC-010): names and signatures only, with constant results and no behaviour. The tests
in tests/unit and tests/integration fail on their assertions against this file.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from fastapi import Request, Response

from diucs.adapters.inbound.fhir_rest.capability import FhirJSONResponse
from diucs.application.actor import Actor
from diucs.application.ports.outbound.cache import Cache

REPLAY_TTL = timedelta(hours=24)


def etag_for(version_id: int) -> str:
    return ""


def versioned_response(
    body: dict[str, Any], *, version_id: int, status_code: int = 200
) -> FhirJSONResponse:
    return FhirJSONResponse(content=body, status_code=status_code)


def parse_if_match(value: str | None) -> int:
    return 0


def require_if_match(request: Request) -> int:
    return 0


def check_version(expected: int, current: int | None) -> None:
    return None


def check_idempotency_key(value: str | None) -> str:
    return ""


def idempotency_key(request: Request) -> str:
    return ""


def body_hash(body: bytes) -> str:
    return ""


def subject_of(actor: Actor) -> str:
    return ""


def scoped_key(sub: str, key: str) -> str:
    return ""


@dataclass(frozen=True, slots=True)
class StoredResponse:
    status_code: int
    headers: dict[str, str]
    body: bytes


class ReplayCache:
    def __init__(self, cache: Cache) -> None:
        self._cache = cache

    async def lookup(self, sub: str, key: str, digest: str) -> StoredResponse | None:
        return None

    async def save(self, sub: str, key: str, digest: str, response: StoredResponse) -> None:
        return None


async def replay_or_run(request: Request, sub: str, key: str, run: Any) -> Response:
    return await run()
