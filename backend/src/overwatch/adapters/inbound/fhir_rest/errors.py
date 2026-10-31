"""OperationOutcome error bodies and their exception mapping (R01).

Every error under /fhir, including 404 for an unknown path and 405, is an OperationOutcome with one
issue. Diagnostics are fixed plain words, never text from the request or from the exception, so no
error body can carry a postcode or a name (DEC-086 items 2 to 5).
"""

import logging
from collections.abc import Mapping, MutableMapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Receive, Scope, Send

from diucs.adapters.inbound.fhir_rest.capability import FhirJSONResponse
from diucs.adapters.inbound.fhir_rest.validation import ProfileRejected, issue_outcome
from diucs.domain.errors import (
    Conflict,
    InvalidTransition,
    NotAllowed,
    NotFound,
    StaleVersion,
    ValidationFailed,
)

log = logging.getLogger(__name__)


class PreconditionFailed(Exception):
    """An If-Match value that does not match the stored version, or cannot match (412, R03)."""


class PreconditionRequired(Exception):
    """A write with no If-Match header (428, R03)."""


class HeaderRefused(Exception):
    """A request header that the API refuses, with the status and code it maps to (R03)."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class RateLimited(Exception):
    """A limit on a route with no token is used up (TEN-040): 429 with Retry-After."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("rate limited")
        self.retry_after_seconds = retry_after_seconds


class TemporarilyUnavailable(Exception):
    """A store a route with no token needs cannot be reached (TEN-040): 503 with Retry-After. The
    cause is logged by class name by the raiser and never reaches the body."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("temporarily unavailable")
        self.retry_after_seconds = retry_after_seconds


NOT_FOUND_TEXT = "The requested resource was not found."
CONFLICT_TEXT = "The change conflicts with the current state of the record."
TRANSITION_TEXT = "This change is not allowed in the current state of the record."
INVALID_REQUEST_TEXT = "The request is not valid."
UNSUPPORTED_MEDIA_TEXT = (
    "The request body type is not supported. Send application/fhir+json or application/json."
)
INTERNAL_TEXT = "Internal error"
METHOD_TEXT = "The HTTP method is not allowed for this resource."
LOGIN_TEXT = "The bearer token is missing, expired or not valid."
RATE_LIMITED_TEXT = "Too many requests. Try again shortly."
UNAVAILABLE_TEXT = "This is not available right now. Try again shortly."
PRECONDITION_FAILED_TEXT = "The If-Match version does not match the current version of the record."
PRECONDITION_REQUIRED_TEXT = (
    "A write without a version is refused. Send If-Match with the version you read."
)

ACCEPTED_BODY_TYPES = frozenset({"application/fhir+json", "application/json"})
# The Twilio webhook (I07) is not FHIR: Twilio posts a form, which this check would refuse.
WEBHOOK_PATH_PREFIX = "/webhooks/"
# The link pages (L01) are not FHIR either: renewing a link is a POST with no body at all, and every
# answer there is the link pages' own, so a bare POST must not be told it has the wrong media type.
LINK_PATH_PREFIX = "/links/"
_BODY_METHODS = frozenset({"POST", "PUT"})
_HTTP_STATUS_TEXT = {404: NOT_FOUND_TEXT, 405: METHOD_TEXT, 415: UNSUPPORTED_MEDIA_TEXT}

# Exception handlers take the exception as Any: Starlette passes whichever class is registered.
DomainHandler = Any


def operation_outcome(
    status: int,
    code: str,
    diagnostics: str,
    expression: str | None = None,
    headers: Mapping[str, str] | None = None,
) -> Response:
    issue: dict[str, Any] = {"severity": "error", "code": code, "diagnostics": diagnostics}
    if expression is not None:
        issue["expression"] = [expression]
    body = {"resourceType": "OperationOutcome", "issue": [issue]}
    return FhirJSONResponse(content=body, status_code=status, headers=headers)


def _fixed(status: int, code: str, text: str) -> DomainHandler:
    def handler(request: Request, exc: Any) -> Response:
        return operation_outcome(status, code, text)

    return handler


def _validation_failed(request: Request, exc: Any) -> Response:
    # The domain message is plain words that name the rule. The domain must keep values out of it.
    assert isinstance(exc, ValidationFailed)
    return operation_outcome(400, "invalid", exc.message, expression=exc.field)


def _profile_rejected(request: Request, exc: Any) -> Response:
    # Every problem, each at its element: the check that refused the body is the profile's (R14).
    assert isinstance(exc, ProfileRejected)
    return FhirJSONResponse(content=issue_outcome(exc.issues), status_code=400)


def _request_invalid(request: Request, exc: Any) -> Response:
    # Only the location is used, never the input value, which may be a postcode.
    assert isinstance(exc, RequestValidationError)
    expression = None
    errors = exc.errors()
    if errors:
        parts = [str(part) for part in errors[0]["loc"] if part not in ("body", "query", "path")]
        expression = ".".join(parts) or None
    return operation_outcome(400, "invalid", INVALID_REQUEST_TEXT, expression=expression)


def _http_error(request: Request, exc: Any) -> Response:
    assert isinstance(exc, StarletteHTTPException)
    status = exc.status_code
    if status == 401:
        # DEC-095: a missing, expired or badly signed bearer token is `login`, not `invalid`.
        return operation_outcome(401, "login", LOGIN_TEXT, headers=exc.headers)
    if status == 404:
        return operation_outcome(404, "not-found", NOT_FOUND_TEXT)
    if status in (405, 415):
        return operation_outcome(status, "not-supported", _HTTP_STATUS_TEXT[status])
    if status < 500:
        return operation_outcome(status, "invalid", INVALID_REQUEST_TEXT)
    return operation_outcome(status, "exception", INTERNAL_TEXT)


def _precondition_failed(request: Request, exc: Any) -> Response:
    return operation_outcome(412, "conflict", PRECONDITION_FAILED_TEXT)


def _precondition_required(request: Request, exc: Any) -> Response:
    return operation_outcome(428, "required", PRECONDITION_REQUIRED_TEXT)


def _header_refused(request: Request, exc: Any) -> Response:
    # The message is one of the fixed texts in concurrency.py; it never echoes the header value.
    assert isinstance(exc, HeaderRefused)
    return operation_outcome(exc.status_code, exc.code, exc.message)


def _rate_limited(request: Request, exc: Any) -> Response:
    assert isinstance(exc, RateLimited)
    return operation_outcome(
        429,
        "throttled",
        RATE_LIMITED_TEXT,
        headers={"Retry-After": str(exc.retry_after_seconds), "Cache-Control": "no-store"},
    )


def _unavailable(request: Request, exc: Any) -> Response:
    assert isinstance(exc, TemporarilyUnavailable)
    return operation_outcome(
        503,
        "transient",
        UNAVAILABLE_TEXT,
        headers={"Retry-After": str(exc.retry_after_seconds), "Cache-Control": "no-store"},
    )


def install_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ValidationFailed, _validation_failed)
    app.add_exception_handler(ProfileRejected, _profile_rejected)
    app.add_exception_handler(NotFound, _fixed(404, "not-found", NOT_FOUND_TEXT))
    app.add_exception_handler(NotAllowed, _fixed(404, "not-found", NOT_FOUND_TEXT))
    app.add_exception_handler(Conflict, _fixed(409, "conflict", CONFLICT_TEXT))
    app.add_exception_handler(InvalidTransition, _fixed(409, "business-rule", TRANSITION_TEXT))
    app.add_exception_handler(RequestValidationError, _request_invalid)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(PreconditionFailed, _precondition_failed)
    # A use case that finds the record at a newer version than the caller read (H-192).
    app.add_exception_handler(StaleVersion, _precondition_failed)
    app.add_exception_handler(PreconditionRequired, _precondition_required)
    app.add_exception_handler(HeaderRefused, _header_refused)
    app.add_exception_handler(RateLimited, _rate_limited)
    app.add_exception_handler(TemporarilyUnavailable, _unavailable)


class BodyTypeMiddleware:
    """A POST or PUT whose body is not application/fhir+json or application/json gets 415, before
    routing (FHIR R4B: any other body type on POST or PUT is refused)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        is_body_request = (
            scope["type"] == "http"
            and scope["method"] in _BODY_METHODS
            and not str(scope["path"]).startswith((WEBHOOK_PATH_PREFIX, LINK_PATH_PREFIX))
        )
        if is_body_request and _body_type(scope) not in ACCEPTED_BODY_TYPES:
            response = operation_outcome(415, "not-supported", UNSUPPORTED_MEDIA_TEXT)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def _body_type(scope: MutableMapping[str, Any]) -> str:
    for name, value in scope["headers"]:
        if name == b"content-type":
            return str(value.decode("latin-1")).split(";", 1)[0].strip().lower()
    return ""


class UnhandledErrorMiddleware:
    """Turns any exception that no handler maps into a 500 OperationOutcome.

    It logs the exception's class name only. The message and the traceback are left out, because
    they can carry a postcode, and the server's own log would otherwise record them (DEC-086
    item 4). If a response has already started, the error cannot be turned into a body, so the
    connection is left to the server.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracking_send(message: MutableMapping[str, Any]) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as error:
            log.error("Unhandled error in the FHIR API: %s", type(error).__name__)
            if started:
                return
            response = operation_outcome(500, "exception", INTERNAL_TEXT)
            await response(scope, receive, send)
