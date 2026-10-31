"""Twilio inbound SMS webhook (I07, DEC-131, DEC-149).

POST /webhooks/sms/twilio takes a text sent to one tenant's number; POST /webhooks/sms/twilio/status
takes a delivery receipt. Both answer Twilio at once and leave the work to the queues.

Order of work, and why it is this order:

1. Read the form. A request with a query string, or a body that is not one plain urlencoded
   Twilio form (wrong type, too large, a field twice, not UTF-8), is refused.
2. Pick the candidate line from `To` and `AccountSid` (a receipt: `AccountSid`) in the inbound line
   directory, and read that subaccount's auth token from the secret store (DEC-131 items 2 and 4).
   Nothing in the body is trusted yet: these fields only choose which token to check against.
3. Verify X-Twilio-Signature over the public URL from settings, not the URL the app saw behind its
   proxy, with a constant-time compare. Only now is the tenant known, and it is bound for the rest
   of the request. The tenant is never taken from the sender, the text, a query string, a header or
   the host.
4. A request that fails any of 1 to 3, including one for a number or account that is not in the
   directory, gets the same 403 with the same fixed body, so a caller learns nothing about which
   numbers or tenants exist and no database is touched.
5. Reply route: hash `From`, look it up through a short read-only unit of work (the allow-list),
   mark the MessageSid in the cache (`SET NX EX`, tenant-prefixed), queue the reply on
   `inbound.replies`. An unknown sender, a replay and a message that cannot be used all get the
   same empty TwiML as an accepted one, so the answer says nothing about who is on the list. If the
   queue send fails the marker is removed and the route answers 500, so Twilio's retry is not
   mistaken for a replay.

No number, message text, phone hash or token is logged: a log line carries a reason and the Twilio
message id. The collaborators are set on `app.state.sms_webhook` by the process that serves the app
(as for the live stream, DEC-096); a missing one is a 500, never a pass.
"""

import base64
import hashlib
import hmac
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, timedelta
from typing import Final, Protocol
from urllib.parse import parse_qsl

from fastapi import APIRouter, Request, Response

from diucs.adapters.outbound.sms_twilio.twilio_sms import parse_status_callback
from diucs.application.ports.outbound.cache import Cache
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.event_bus import BusMessage, EventBus
from diucs.application.ports.outbound.identity import PhoneHasher
from diucs.application.ports.outbound.tenant_lines import InboundLine, InboundLineDirectory
from diucs.application.ports.outbound.tokens import SecretStore
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import ScopeId, ScopeInvalid, bind_tenant, current_tenant
from diucs.domain.errors import Conflict, NotFound, ValidationFailed

log = logging.getLogger(__name__)

REPLY_PATH: Final = "/webhooks/sms/twilio"
STATUS_PATH: Final = "/webhooks/sms/twilio/status"
REPLIES_QUEUE: Final = "inbound.replies"
RECEIPTS_QUEUE: Final = "inbound.receipts"
REPLY_EVENT: Final = "SmsReceived"
RECEIPT_EVENT: Final = "SmsDeliveryReceived"

# architecture.md, F1: a replayed MessageSid is ignored for a day.
REPLAY_TTL: Final = timedelta(hours=24)
# Twilio's own limit for an inbound text is 1,600 characters. A form larger than 64 KiB, or with
# more than 100 fields, is not a Twilio form.
MAX_TEXT_CHARS: Final = 1600
MAX_FORM_BYTES: Final = 64 * 1024
MAX_FORM_FIELDS: Final = 100

_FORM_TYPE: Final = "application/x-www-form-urlencoded"
_SIGNATURE_HEADER: Final = "x-twilio-signature"
# Twilio sids are two letters and 32 hex digits. The pattern is looser (the tests and the receipt
# vocabulary use short ids) but safe in a cache key, a bus message id and a log line: no colon.
_SID: Final = re.compile(r"[A-Za-z0-9]{2,64}")
_E164: Final = re.compile(r"\+[1-9][0-9]{6,14}")

_TWIML: Final = b'<?xml version="1.0" encoding="UTF-8"?><Response/>'
_REFUSED_BODY: Final = b"Forbidden"


@dataclass(frozen=True, slots=True)
class SmsWebhookDeps:
    """What the webhook needs besides the container's clock and unit of work. Set on
    `app.state.sms_webhook` by the process that serves the app."""

    cache: Cache
    event_bus: EventBus
    hasher: PhoneHasher
    secrets: SecretStore
    lines: InboundLineDirectory
    # The public base URL from settings (Settings.base_url): the URL Twilio signed, not the URL
    # the app sees behind a proxy.
    public_base_url: str


class _Container(Protocol):
    @property
    def clock(self) -> Clock: ...

    @property
    def uow_factory(self) -> UnitOfWorkFactory: ...


def twilio_signature(url: str, params: Mapping[str, str], token: str | bytes) -> str:
    """base64(HMAC-SHA1(token, url + each POST parameter's name and value, sorted by name))."""
    key = token.encode("utf-8") if isinstance(token, str) else token
    data = url + "".join(name + params[name] for name in sorted(params))
    digest = hmac.new(key, data.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("ascii")


def replay_key(message_sid: str) -> str:
    """The cache key that marks a MessageSid as seen, from the bound tenant (never a default: no
    tenant bound is an error). The one place it is built, so the cache adapter's own tenant prefix
    (DEC-130 item 7) is added in one step later."""
    return f"idem:sms:{current_tenant()}:{message_sid}"


def _twiml() -> Response:
    return Response(content=_TWIML, status_code=200, headers={"content-type": "text/xml"})


def _refused(reason: str) -> Response:
    # One status, one header set and one body for every refusal. The reason goes to the log only.
    log.warning("sms webhook refused: reason=%s", reason)
    return Response(content=_REFUSED_BODY, status_code=403, headers={"content-type": "text/plain"})


def _dropped(reason: str, message_sid: str) -> Response:
    shown = message_sid if _SID.fullmatch(message_sid) else "-"
    log.info("sms dropped: reason=%s message_sid=%s", reason, shown)
    return _twiml()


async def _read_form(request: Request) -> dict[str, str] | None:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != _FORM_TYPE:
        return None
    declared = request.headers.get("content-length")
    if declared is not None and (not declared.isdecimal() or int(declared) > MAX_FORM_BYTES):
        return None
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_FORM_BYTES:
            return None
    try:
        pairs = parse_qsl(
            body.decode("utf-8"),
            keep_blank_values=True,
            strict_parsing=False,
            errors="strict",
            max_num_fields=MAX_FORM_FIELDS,
        )
    except ValueError:  # not UTF-8, or too many fields
        return None
    names = [name for name, _ in pairs]
    if len(set(names)) != len(names):  # Twilio never repeats a name
        return None
    return dict(pairs)


async def _verified(
    request: Request, deps: SmsWebhookDeps, path: str, *, by_number: bool
) -> tuple[InboundLine, dict[str, str]] | Response:
    """The line and the form of a request whose signature verifies, or the refusal."""
    if request.url.query:
        # Twilio calls the URL it was given, which has no query here, and nothing is read from one.
        return _refused("query")
    form = await _read_form(request)
    if form is None:
        return _refused("form")
    signature = request.headers.get(_SIGNATURE_HEADER, "")
    account_sid = form.get("AccountSid", "")
    if not signature or _SID.fullmatch(account_sid) is None:
        return _refused("signature-or-account-missing")
    if by_number:
        number = form.get("To", "")
        if _E164.fullmatch(number) is None:
            return _refused("number-malformed")
        line = await deps.lines.for_number(number, account_sid)
    else:
        line = await deps.lines.for_account(account_sid)
    if line is None:
        return _refused("line-unknown")
    try:
        ScopeId.tenant(line.tenant_id)
    except ScopeInvalid:
        log.error("an inbound line has a tenant id that is not valid")
        return _refused("line-invalid")
    try:
        token = deps.secrets.get(line.token_secret)
    except NotFound:
        log.error(
            "an inbound line has no auth token in the secret store: tenant=%s", line.tenant_id
        )
        return _refused("token-missing")
    expected = twilio_signature(deps.public_base_url.rstrip("/") + path, form, token)
    if not hmac.compare_digest(expected.encode("ascii"), signature.encode("latin-1")):
        return _refused("signature-bad")
    return line, form


def _deps(request: Request) -> tuple[SmsWebhookDeps, _Container]:
    # Fail closed: a missing collaborator is a configuration error (a 500), never an open route.
    deps: SmsWebhookDeps | None = getattr(request.app.state, "sms_webhook", None)
    container: _Container | None = getattr(request.app.state, "container", None)
    if deps is None or container is None:
        raise RuntimeError("the SMS webhook is not configured")
    return deps, container


router = APIRouter()


@router.post(REPLY_PATH)
async def sms_reply(request: Request) -> Response:
    deps, container = _deps(request)
    verified = await _verified(request, deps, REPLY_PATH, by_number=True)
    if isinstance(verified, Response):
        return verified
    line, form = verified
    with bind_tenant(line.tenant_id):
        return await _accept_reply(deps, container, form)


async def _accept_reply(
    deps: SmsWebhookDeps, container: _Container, form: Mapping[str, str]
) -> Response:
    sid = form.get("MessageSid", "")
    text = form.get("Body", "")
    if _SID.fullmatch(sid) is None or not text.strip() or len(text) > MAX_TEXT_CHARS:
        return _dropped("unusable-message", sid)
    try:
        phone_hash = deps.hasher.hash(form.get("From", ""))
    except ValidationFailed:
        return _dropped("sender-not-a-mobile", sid)
    try:
        async with container.uow_factory() as uow:
            person = await uow.people.find_by_phone_hash(phone_hash)
    except Conflict:
        return _dropped("sender-ambiguous", sid)
    if person is None:
        return _dropped("sender-unknown", sid)
    key = replay_key(sid)
    if not await deps.cache.set_if_absent(key, "1", REPLAY_TTL):
        return _dropped("replay", sid)
    message = BusMessage(
        id=sid,
        topic=REPLIES_QUEUE,
        event_type=REPLY_EVENT,
        payload={
            "phone_hash": phone_hash,
            "text": text,
            "received_at": container.clock.now().astimezone(UTC).isoformat(),
            "provider_message_id": sid,
        },
        tenant_id=current_tenant(),
    )
    try:
        await deps.event_bus.enqueue(REPLIES_QUEUE, message)
    except BaseException:
        # Not queued, so Twilio's retry must not look like a replay.
        await _release(deps.cache, key)
        raise
    log.info("sms reply queued: message_sid=%s", sid)
    return _twiml()


async def _release(cache: Cache, key: str) -> None:
    try:
        await cache.delete(key)
    except Exception as error:
        log.error("the replay marker could not be removed: %s", type(error).__name__)


@router.post(STATUS_PATH)
async def sms_status(request: Request) -> Response:
    deps, _ = _deps(request)
    verified = await _verified(request, deps, STATUS_PATH, by_number=False)
    if isinstance(verified, Response):
        return verified
    line, form = verified
    with bind_tenant(line.tenant_id):
        return await _accept_receipt(deps, form)


async def _accept_receipt(deps: SmsWebhookDeps, form: Mapping[str, str]) -> Response:
    sid = form.get("MessageSid", "")
    if _SID.fullmatch(sid) is None:
        return _dropped("unusable-receipt", sid)
    try:
        update = parse_status_callback(form)
    except ValueError:  # a status the system does not map (accepted, read, ...)
        return _dropped("status-not-mapped", sid)
    message = BusMessage(
        id=f"{sid}:{form['MessageStatus']}",
        topic=RECEIPTS_QUEUE,
        event_type=RECEIPT_EVENT,
        payload={
            "provider_message_id": update.provider_message_id,
            "status": update.status,
            "error_code": update.error_code,
        },
        tenant_id=current_tenant(),
    )
    await deps.event_bus.enqueue(RECEIPTS_QUEUE, message)
    log.info("sms receipt queued: message_sid=%s status=%s", sid, update.status)
    return _twiml()
