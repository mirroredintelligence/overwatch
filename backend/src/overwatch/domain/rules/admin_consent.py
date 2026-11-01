"""Admin consent of an organisation's Entra administrator (DEC-1316).

Pure: no I/O and no clock. An organisation's Entra administrator is sent a link that asks them to
let our staff sign-in app in their directory. The link carries an opaque `state`; the invite is
recorded as pending and becomes consented only after the platform has seen, through Microsoft
Graph in that directory, that the app is installed. A redirect alone is never proof.

- The state is `<tenant id>.<43 random url-safe characters>` (256 bits). Only the SHA-256 of the
  whole state is stored. The tenant id in front is a routing hint for the public return route,
  which has no host to name a tenant: it binds that tenant, and the invite is then looked up by
  hash inside it. A hint that names the wrong tenant finds nothing, so it grants nothing.
- The administrator's address is kept as a keyed hash (for matching) and a masked form (for the
  operator's page). The address in the clear is used for the one send and is not stored.
- An invite is valid for seven days. `effective_status` turns a pending invite past its expiry into
  expired without a write.
"""

import hashlib
import hmac
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from secrets import token_urlsafe
from typing import Final
from urllib.parse import urlencode

from overwatch.domain.errors import ValidationFailed
from overwatch.domain.model.tenant import TENANT_ID_PATTERN
from overwatch.domain.model.tenant_records import DIRECTORY_ID_PATTERN

INVITE_VALID_FOR: Final = timedelta(days=7)
STATE_RANDOM_BYTES: Final = 32
STATE_SEPARATOR: Final = "."
CONSENT_ENDPOINT: Final = "https://login.microsoftonline.com/{directory}/adminconsent"
REQUIRED_APP_ROLE: Final = "Group.ReadWrite.All"
"""The Graph application permission whose grant proves the consent covers what we need."""

EMAIL_MAX: Final = 254
_EMAIL: Final = re.compile(
    r"[A-Za-z0-9._%+'-]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?"
)
_STATE: Final = re.compile(r"([a-z0-9][a-z0-9-]{1,30})\.([A-Za-z0-9_-]{43})")
_HASH: Final = re.compile(r"[0-9a-f]{64}")
_EMAIL_HASH_DOMAIN: Final = b"admin-consent-email\x00"

EMAIL_MESSAGE: Final = "give the administrator's work email address"
STATE_MESSAGE: Final = "the state is not one of ours"


class InviteStatus(StrEnum):
    PENDING = "pending"
    CONSENTED = "consented"
    REVOKED = "revoked"


class EffectiveStatus(StrEnum):
    """What the operator sees: the stored status, with a pending invite past its time as expired."""

    PENDING = "pending"
    CONSENTED = "consented"
    EXPIRED = "expired"
    REVOKED = "revoked"


@dataclass(frozen=True, slots=True)
class AdminConsentInvite:
    """One invitation. The tenant is the scope it is stored in (it has no tenant field)."""

    invite_id: str
    directory_id: str
    email_hash: str
    email_masked: str
    state_hash: str
    status: InviteStatus
    created_at: datetime
    expires_at: datetime
    consented_at: datetime | None = None
    revoked_at: datetime | None = None
    last_reason: str | None = None
    """The words for why the last check did not confirm the consent; None before any check."""

    def __post_init__(self) -> None:
        if DIRECTORY_ID_PATTERN.fullmatch(self.directory_id) is None:
            raise ValidationFailed("directory_id", "not a directory id")
        for name in ("email_hash", "state_hash"):
            if _HASH.fullmatch(getattr(self, name)) is None:
                raise ValidationFailed(name, "not a hash")
        for name in ("created_at", "expires_at", "consented_at", "revoked_at"):
            value = getattr(self, name)
            if value is not None and value.utcoffset() is None:
                raise ValidationFailed(name, "a time must carry its zone")
        if self.expires_at <= self.created_at:
            raise ValidationFailed("expires_at", "an invite expires after it is made")
        if (self.status is InviteStatus.CONSENTED) != (self.consented_at is not None):
            raise ValidationFailed("consented_at", "consented and its time go together")
        if (self.status is InviteStatus.REVOKED) != (self.revoked_at is not None):
            raise ValidationFailed("revoked_at", "revoked and its time go together")


def effective_status(invite: AdminConsentInvite, now: datetime) -> EffectiveStatus:
    if invite.status is InviteStatus.CONSENTED:
        return EffectiveStatus.CONSENTED
    if invite.status is InviteStatus.REVOKED:
        return EffectiveStatus.REVOKED
    return EffectiveStatus.EXPIRED if now >= invite.expires_at else EffectiveStatus.PENDING


def check_email(value: object) -> str:
    """The address, trimmed and in lower case, when it is one plain address. The refusal does not
    echo it."""
    if type(value) is not str:
        raise ValidationFailed("email", EMAIL_MESSAGE)
    email = value.strip().lower()
    if len(email) > EMAIL_MAX or _EMAIL.fullmatch(email) is None or ".." in email:
        raise ValidationFailed("email", EMAIL_MESSAGE)
    return email


def hash_email(email: str, secret: bytes) -> str:
    """HMAC-SHA256 of the normalised address under the platform secret, in hex."""
    message = _EMAIL_HASH_DOMAIN + check_email(email).encode("ascii")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def mask_email(email: str) -> str:
    """`a***@example.org`: the first letter of the local part and the whole domain."""
    local, _, domain = check_email(email).partition("@")
    return f"{local[0]}***@{domain}"


def new_state(tenant_id: str, rng: Callable[[int], str] = token_urlsafe) -> str:
    """A new state for this tenant. `rng` gives url-safe text from the given number of bytes."""
    if TENANT_ID_PATTERN.fullmatch(tenant_id) is None:
        raise ValidationFailed("tenant_id", "not a tenant id")
    random = rng(STATE_RANDOM_BYTES)
    state = f"{tenant_id}{STATE_SEPARATOR}{random}"
    if _STATE.fullmatch(state) is None:
        raise ValidationFailed("state", STATE_MESSAGE)
    return state


def hash_state(state: str) -> str:
    return hashlib.sha256(state.encode("ascii")).hexdigest()


def tenant_hint(state: object) -> str | None:
    """The tenant id a state names, or None when the text is not a state. A hint only."""
    if type(state) is not str or not state.isascii():
        return None
    match = _STATE.fullmatch(state)
    return None if match is None else match.group(1)


def consent_url(directory_id: str, client_id: str, redirect_uri: str, state: str) -> str:
    if DIRECTORY_ID_PATTERN.fullmatch(directory_id) is None:
        raise ValidationFailed("directory_id", "not a directory id")
    query = urlencode({"client_id": client_id, "redirect_uri": redirect_uri, "state": state})
    return f"{CONSENT_ENDPOINT.format(directory=directory_id)}?{query}"
