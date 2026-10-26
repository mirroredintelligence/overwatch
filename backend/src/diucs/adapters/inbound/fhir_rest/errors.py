"""OperationOutcome error bodies and their exception mapping (R01).

Every error under /fhir, including 404 for an unknown path and 405, is an OperationOutcome with one
issue. Diagnostics are fixed plain words, never text from the request or from the exception, so no
error body can carry a postcode or a name (DEC-085 items 2 to 5).
"""

import logging
from collections.abc import MutableMapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Receive, Scope, Send

from diucs.adapters.inbound.fhir_rest.capability import FhirJSONResponse
from diucs.domain.errors import Conflict, InvalidTransition, NotAllowed, NotFound, ValidationFailed

log = logging.getLogger(__name__)

NOT_FOUND_TEXT = "The requested resource was not found."
CONFLICT_TEXT = "The change conflicts with the current state of the record."
TRANSITION_TEXT = "This change is not allowed in the current state of the record."
INVALID_REQUEST_TEXT = "The request is not valid."
UNSUPPORTED_MEDIA_TEXT = (
    "The request body type is not supported. Send application/fhir+json or application/json."
)
INTERNAL_TEXT = "Internal error"
METHOD_TEXT = "The HTTP method is not allowed for this resource."

ACCEPTED_BODY_TYPES = frozenset({"application/fhir+json", "application/json"})
_BODY_METHODS = frozenset({"POST", "PUT"})
_HTTP_STATUS_TEXT = {404: NOT_FOUND_TEXT, 405: METHOD_TEXT, 415: UNSUPPORTED_MEDIA_TEXT}

# Exception handlers take the exception as Any: Starlette passes whichever class is registered.
DomainHandler = Any


def operation_outcome(
    status: int, code: str, diagnostics: str, expression: str | None = None
) -> Response:
    issue: dict[str, Any] = {"severity": "error", "code": code, "diagnostics": diagnostics}
    if expression is not None:
        issue["expression"] = [expression]
    body = {"resourceType": "OperationOutcome", "issue": [issue]}
    return FhirJSONResponse(content=body, status_code=status)


def _fixed(status: int, code: str, text: str) -> DomainHandler:
    def handler(request: Request, exc: Any) -> Response:
        return operation_outcome(status, code, text)

    return handler


def _validation_failed(request: Request, exc: Any) -> Response:
    # The domain message is plain words that name the rule. The domain must keep values out of it.
    assert isinstance(exc, ValidationFailed)
    return operation_outcome(400, "invalid", exc.message, expression=exc.field)


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
    if status == 404:
        return operation_outcome(404, "not-found", NOT_FOUND_TEXT)
    if status in (405, 415):
        return operation_outcome(status, "not-supported", _HTTP_STATUS_TEXT[status])
    if status < 500:
        return operation_outcome(status, "invalid", INVALID_REQUEST_TEXT)
    return operation_outcome(status, "exception", INTERNAL_TEXT)


def install_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ValidationFailed, _validation_failed)
    app.add_exception_handler(NotFound, _fixed(404, "not-found", NOT_FOUND_TEXT))
    app.add_exception_handler(NotAllowed, _fixed(404, "not-found", NOT_FOUND_TEXT))
    app.add_exception_handler(Conflict, _fixed(409, "conflict", CONFLICT_TEXT))
    app.add_exception_handler(InvalidTransition, _fixed(409, "business-rule", TRANSITION_TEXT))
    app.add_exception_handler(RequestValidationError, _request_invalid)
    app.add_exception_handler(StarletteHTTPException, _http_error)


class BodyTypeMiddleware:
    """A POST or PUT whose body is not application/fhir+json or application/json gets 415, before
    routing (FHIR R4B: any other body type on POST or PUT is refused)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        is_body_request = scope["type"] == "http" and scope["method"] in _BODY_METHODS
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
    they can carry a postcode, and the server's own log would otherwise record them (DEC-085
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
