"""ETag, If-Match and Idempotency-Key handling for the FHIR API (R03, DEC-101).

Reads of a versioned resource carry `ETag: W/"<versionId>"`. A write to one sends If-Match with the
version it read: no If-Match is 428, a version that does not match is 412 (check_version). A create
sends Idempotency-Key. The first successful response is cached for 24 hours under
`idem:<sub>:<key>` with a SHA-256 of the request body, so a repeat with the same key and body is
answered from the cache and the use case does not run. A different body is 422. The cache is only
the fast guard: the use case also passes the key into its durable IdempotencyStore (P15), which
holds after the cache entry expires or Redis restarts. Request bodies are hashed, never stored.
The process that serves the app sets `app.state.cache` (a Cache port); with none, a write fails
closed with a 500 (DEC-096 pattern).
"""

import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Final

from fastapi import Request, Response

from diucs.adapters.inbound.fhir_rest.capability import FhirJSONResponse
from diucs.adapters.inbound.fhir_rest.errors import (
    HeaderRefused,
    PreconditionFailed,
    PreconditionRequired,
)
from diucs.application.actor import Actor
from diucs.application.ports.outbound.cache import Cache

REPLAY_TTL: Final = timedelta(hours=24)
REPLAY_HEADER: Final = "Idempotent-Replay"
_KEY_PATTERN: Final = re.compile(r"[\x21-\x7e]{1,200}")
_IF_MATCH_PATTERN: Final = re.compile(r'W/"([1-9][0-9]{0,17})"')
_KEPT_HEADERS: Final = ("ETag", "Location", "Content-Type")
_KEY_REQUIRED: Final = "An Idempotency-Key header is required on this request."
_KEY_INVALID: Final = "The Idempotency-Key header is not valid."
_KEY_REUSED: Final = "This key was used for a different request."


def etag_for(version_id: int) -> str:
    return f'W/"{version_id}"'


def versioned_response(
    body: dict[str, Any], *, version_id: int, status_code: int = 200
) -> FhirJSONResponse:
    """A FHIR body with meta.versionId set to the version, and the matching weak ETag."""
    meta = dict(body.get("meta") or {})
    meta["versionId"] = str(version_id)
    content = {**body, "meta": meta}
    return FhirJSONResponse(
        content=content, status_code=status_code, headers={"ETag": etag_for(version_id)}
    )


def parse_if_match(value: str | None) -> int:
    """The version an If-Match names. Missing is 428. Anything that is not a weak tag of a
    version number cannot match a stored version, so it is 412."""
    if value is None:
        raise PreconditionRequired()
    match = _IF_MATCH_PATTERN.fullmatch(value)
    if match is None:
        raise PreconditionFailed()
    return int(match.group(1))


def require_if_match(request: Request) -> int:
    return parse_if_match(request.headers.get("if-match"))


def check_version(expected: int, current: int | None) -> None:
    """412 unless the stored version is the one the caller read. A missing version never matches.
    Call it after the record's write lock is taken, or two writers can both pass (lesson L63)."""
    if current is None or expected != current:
        raise PreconditionFailed()


def check_idempotency_key(value: str | None) -> str:
    if value is None or value == "":
        raise HeaderRefused(400, "required", _KEY_REQUIRED)
    if _KEY_PATTERN.fullmatch(value) is None:
        raise HeaderRefused(400, "invalid", _KEY_INVALID)
    return value


def idempotency_key(request: Request) -> str:
    return check_idempotency_key(request.headers.get("idempotency-key"))


def body_hash(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def subject_of(actor: Actor) -> str:
    """The `sub` of the token: the practitioner, or the device for a wall screen."""
    sub = actor.practitioner_id if actor.practitioner_id is not None else actor.device_id
    if not sub:
        raise ValueError("an actor with no subject cannot make an idempotent write")
    return sub


def scoped_key(sub: str, key: str) -> str:
    """The name of a key for one subject. A colon in the subject could make two pairs share a
    name, so such a subject is refused (subjects are system ids and have none)."""
    if not sub or ":" in sub:
        raise ValueError("a subject with no text or with a colon cannot own a replay key")
    return f"idem:{sub}:{key}"


@dataclass(frozen=True, slots=True)
class StoredResponse:
    status_code: int
    headers: dict[str, str]
    body: bytes


class ReplayCache:
    """The 24-hour fast guard. Stores the request digest and the response, never the request."""

    def __init__(self, cache: Cache) -> None:
        self._cache = cache

    async def lookup(self, actor: Actor, key: str, body_hash: str) -> StoredResponse | None:
        text = await self._cache.get(scoped_key(subject_of(actor), key))
        if text is None:
            return None
        try:
            payload = json.loads(text)
            stored_digest = str(payload["digest"])
            status_code = int(payload["status"])
            headers = {str(k): str(v) for k, v in dict(payload["headers"]).items()}
            body = str(payload["body"]).encode("utf-8")
        except ValueError, KeyError, TypeError:
            # An unreadable entry is a miss. The use case's durable store still refuses a repeat.
            return None
        if stored_digest != body_hash:
            raise HeaderRefused(422, "conflict", _KEY_REUSED)
        return StoredResponse(status_code=status_code, headers=headers, body=body)

    async def save(self, actor: Actor, key: str, body_hash: str, response: StoredResponse) -> None:
        text = json.dumps(
            {
                "digest": body_hash,
                "status": response.status_code,
                "headers": response.headers,
                "body": response.body.decode("utf-8"),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        await self._cache.set(scoped_key(subject_of(actor), key), text, REPLAY_TTL)


def _replay_cache(request: Request) -> ReplayCache:
    cache: Cache | None = getattr(request.app.state, "cache", None)
    if cache is None:
        # Fail closed: a write is never run without its replay guard.
        raise RuntimeError("no cache is configured for idempotent writes")
    return ReplayCache(cache)


async def replay_or_run(
    request: Request, actor: Actor, key: str, run: Callable[[], Awaitable[Response]]
) -> Response:
    """Answer a repeat from the cache, or run the write and cache its successful response.

    A failed response is not cached, so a refused request can be retried. The body must be read
    before the run, because the digest is the request's identity."""
    replay = _replay_cache(request)
    digest = body_hash(await request.body())
    stored = await replay.lookup(actor, key, digest)
    if stored is not None:
        return Response(
            content=stored.body,
            status_code=stored.status_code,
            headers={**stored.headers, REPLAY_HEADER: "true"},
        )
    response = await run()
    if 200 <= response.status_code < 300:
        headers = {
            name: response.headers[name] for name in _KEPT_HEADERS if name in response.headers
        }
        await replay.save(
            actor,
            key,
            digest,
            StoredResponse(
                status_code=response.status_code,
                headers=headers,
                body=bytes(response.body),
            ),
        )
    return response
