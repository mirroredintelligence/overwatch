"""Phone hashing for identity lookups (P10, H-09). A phone number is stored only as a keyed hash.

The hash is HMAC-SHA256 with the secret `phone-hash`, over the normalised UK mobile number (eleven
digits starting 07), so "+44 7700 900123" and "07700 900123" are the same subscriber. A number is
never echoed in an error. Decisions: DEC-057.

The key is the secret store's `phone-hash`. In the running process the store is a
`TenantKeyedSecrets` (TEN-023, DEC-350), so the key is the bound tenant's own: the same number is
one hash in a tenant and another in the next, and `hash()` needs a tenant bound.
"""

import hashlib
import hmac
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Protocol

from diucs.application.ports.outbound.tokens import SecretStore
from diucs.application.tenancy import current_tenant
from diucs.domain.codes import Role
from diucs.domain.errors import DomainError, NotFound, ValidationFailed
from diucs.domain.model.device import Device
from diucs.domain.rules.identity_policy import CodeState, PinState
from diucs.domain.rules.tenant_keys import PER_TENANT_KEY_NAMES, derive_tenant_key, uses_legacy_key

PHONE_HASH_SECRET: Final = "phone-hash"
DEVICE_TOKEN_SECRET: Final = "device-token"

_SEPARATORS: Final = re.compile(r"[ \-().]")
_UK_MOBILE: Final = re.compile(r"07[0-9]{9}")


class TenantKeyedSecrets:
    """The process's secret store seen by one tenant at a time (TEN-023, DEC-350).

    A name that is a hash or token key (`PER_TENANT_KEY_NAMES`) is returned as the bound tenant's
    own key, derived from the platform secret with the tenant as context, so every use case that
    reads `phone-hash`, `link-token`, `link-csrf`, `code-hmac`, `pin-hmac`, `device-token` or
    `support-code` gets a key that opens that tenant's hashes and no other's. The default tenant
    keeps the platform secret itself (hash key version 0). Any other name is read as it is.

    A keyed name read with no tenant bound (or a network scope bound) raises TenantNotBound: it
    fails closed, and never falls back to the platform key. A name the platform does not hold is
    NotFound whatever is bound. No derived key is kept, shown or logged."""

    def __init__(self, platform: SecretStore) -> None:
        self._platform = platform

    def get(self, name: str) -> bytes:
        platform_key = self._platform.get(name)
        if name not in PER_TENANT_KEY_NAMES:
            return platform_key
        tenant = current_tenant()
        if uses_legacy_key(tenant):
            return platform_key
        return derive_tenant_key(platform_key, tenant, name)

    def is_configured(self, name: str) -> bool:
        """Whether the platform holds this secret. Reads no key and needs no tenant, so a route can
        check its configuration before it knows whose request it is."""
        try:
            self._platform.get(name)
        except NotFound:
            return False
        return True

    def __repr__(self) -> str:
        return "TenantKeyedSecrets()"


def secret_is_configured(store: SecretStore, name: str) -> bool:
    """Whether the store holds a secret, without needing a tenant for a keyed one."""
    if isinstance(store, TenantKeyedSecrets):
        return store.is_configured(name)
    try:
        store.get(name)
    except NotFound:
        return False
    return True


class PhoneHasher(Protocol):
    def hash(self, number: str) -> str: ...


class HmacPhoneHasher:
    def __init__(self, secrets: SecretStore) -> None:
        self._secrets = secrets

    def hash(self, number: str) -> str:
        national = normalise_uk_mobile(number)
        key = self._secrets.get(PHONE_HASH_SECRET)
        return hmac.new(key, national.encode("ascii"), hashlib.sha256).hexdigest()


def normalise_uk_mobile(number: str) -> str:
    """Return the national form of a UK mobile number: eleven digits, starting 07.

    Accepted: national ("07700 900123"), +44 ("+44 7700 900123", "+44 (0)7700 900123") and 0044.
    Anything else, including a landline or a number of the wrong length, is refused as
    ValidationFailed on the field "phone", without the number in the message.
    """
    if not isinstance(number, str):
        raise ValidationFailed("phone", "must be text")
    compact = _SEPARATORS.sub("", number)
    if compact.startswith("+44"):
        national = "0" + compact[3:].removeprefix("0")
    elif compact.startswith("0044"):
        national = "0" + compact[4:]
    else:
        national = compact
    if not _UK_MOBILE.fullmatch(national):
        raise ValidationFailed("phone", "must be a UK mobile number")
    return national


class ContactStore(Protocol):
    """Protected phone numbers and role emails (P16). Only this port reads them."""

    async def put_phone(self, role_id: str, number: str) -> None: ...

    async def get_phone(self, role_id: str) -> str | None: ...

    async def put_email(self, role_id: str, email: str) -> None: ...

    async def get_email(self, role_id: str) -> str | None: ...


class CodeSender(Protocol):
    """Sends a text code to a phone (U25). The code is sent, never stored by the sender."""

    async def send_code(self, phone: str, code: str) -> None: ...


class CodeResendRefused(DomainError):
    """A new text code was saved less than the resend cooldown after the code it replaces. Carries
    no data: neither the phone hash nor a code is ever put in the message (I13)."""

    def __init__(self) -> None:
        super().__init__("a new code is not allowed yet")


class CodeStore(Protocol):
    """Short-lived text-code state, keyed by (tenant, purpose, phone hash). Redis in production
    (I13). A code issued for one purpose is never found for another, and each purpose has its own
    resend cooldown. Only a hash of the code is stored; the caller hashes it. Saving a different
    code less than the resend cooldown after the stored one, for the same purpose and phone, raises
    CodeResendRefused. A purpose that is not a plain name raises ValidationFailed."""

    async def save(
        self, purpose: str, phone_hash: str, code_hash: str, state: CodeState
    ) -> None: ...

    async def get(self, purpose: str, phone_hash: str) -> tuple[str, CodeState] | None: ...

    async def clear(self, purpose: str, phone_hash: str) -> None: ...


@dataclass(frozen=True, slots=True)
class ReporterSession:
    """A signed-in reporter or COO user. Short-lived, held in Redis, never a record (I13)."""

    session_id: str
    role: Role
    practitioner_id: str
    device_id: str
    services: tuple[str, ...]
    created: datetime
    last_seen: datetime
    epoch: int = 0
    """The person's session epoch when this session began. A session whose epoch is not the
    person's current epoch is dead (U37: sign out everywhere raises the epoch)."""


class SessionEpochChanged(DomainError):
    """A session could not be created because the person's epoch moved after the caller read it:
    they were signed out everywhere in between. Carries no data (U37)."""

    def __init__(self) -> None:
        super().__init__("the person was signed out in the meantime")


class SessionStore(Protocol):
    """Reporter sessions, bound to the tenant of the unit of work (I13). Losing them signs people
    out. A session id is never logged."""

    async def epoch(self, practitioner_id: str) -> int:
        """The person's current session epoch in the bound tenant: 0 until they are first signed
        out everywhere. A sign-in reads it before it checks the PIN and passes it to `create`."""
        ...

    async def create(
        self,
        role: Role,
        practitioner_id: str,
        device_id: str,
        services: tuple[str, ...],
        now: datetime,
        *,
        epoch: int,
    ) -> str:
        """Start a session and return its new random id (256 bits, urlsafe). `epoch` is the value
        `epoch()` gave before the sign-in checked anything; when the person's epoch has moved since
        (a sign out everywhere, a removal), nothing is created and SessionEpochChanged is raised, so
        a sign-in that raced a revoke can never leave a live session behind (U37)."""
        ...

    async def get(self, session_id: str) -> ReporterSession | None:
        """The session while it is live in the bound tenant, or None (also None when its epoch is
        not the person's current one). Does not extend it."""
        ...

    async def touch(self, session_id: str, now: datetime) -> bool:
        """Record activity and extend the session's life to the full TTL. False when it is gone."""
        ...

    async def delete(self, session_id: str) -> None:
        """End one session. A missing session is not an error."""
        ...

    async def delete_all_for_person(self, practitioner_id: str) -> None:
        """End every session of one practitioner in the bound tenant ("sign out of every phone")
        and raise the person's epoch, in one step: a session that was being created at the same
        moment carries the old epoch and is dead on arrival (U37)."""
        ...


class RateLimiter(Protocol):
    """A fixed-window throttle (I13). `allow` counts one attempt under `key` in the bound tenant and
    returns False once `limit` attempts have been counted in the current window. It is a fast
    throttle only; the durable PIN lock lives on the credential in Neo4j."""

    async def allow(self, key: str, limit: int, window: timedelta) -> bool: ...


class PinStore(Protocol):
    """PIN hashes and their lock state, one credential per practitioner and device (P16)."""

    async def set_pin(self, practitioner_id: str, device_id: str, pin_hash: str) -> None: ...

    async def get(self, practitioner_id: str, device_id: str) -> tuple[str, PinState] | None: ...

    async def save_state(self, practitioner_id: str, device_id: str, state: PinState) -> None: ...

    async def clear_all(self, practitioner_id: str) -> None: ...


@dataclass(frozen=True, slots=True)
class DeviceFacts:
    """One of a practitioner's devices as the registry holds it: its id, whether it is active or
    waits for the lead's call-back, when it was registered and when a text code was last verified
    on it. Never revoked ones. Read for the set-up tracker (W7B C); no number is here."""

    device_id: str
    status: str
    registered_at: datetime
    last_verified_at: datetime | None


class DeviceRegistry(Protocol):
    """The devices a practitioner has registered (P16), and the wall screens of the tenant (U10).
    A revoked device is never known again."""

    async def register(self, practitioner_id: str, device_id: str, at: datetime) -> None: ...

    async def known(self, practitioner_id: str, device_id: str) -> bool: ...

    async def count_active(self, practitioner_id: str) -> int:
        """How many of the practitioner's devices are active: registered, not revoked and not
        waiting for the lead's call-back (W7C: the settings count the other phones)."""
        ...

    async def revoke_all(self, practitioner_id: str) -> int:
        """Revoke every device of the practitioner that is not revoked already, pending ones
        included, and return how many were revoked (U37)."""
        ...

    async def register_pending(self, practitioner_id: str, device_id: str, at: datetime) -> None:
        """Register a device that waits for the lead's call-back (U37 lost phone): it is not
        `known`, so it cannot sign in, until `confirm_pending`. Registering a device id that is
        already registered for the practitioner changes nothing (a revoked device stays revoked);
        one held by another practitioner is Conflict."""
        ...

    async def confirm_pending(self, practitioner_id: str, at: datetime) -> int:
        """Make the practitioner's devices that wait for a call-back active, and return how many
        (U37). Zero when none waits."""
        ...

    async def awaiting_callback(self, practitioner_id: str) -> list[str]:
        """The ids of the practitioner's devices that wait for the lead's call-back and are not
        revoked (U37)."""
        ...

    async def devices_of(self, practitioner_id: str) -> list[DeviceFacts]:
        """The practitioner's devices that are not revoked, oldest first (W7B C: the lead's set-up
        tracker). An unknown practitioner, and another tenant's, has none."""
        ...

    async def owner_of(self, device_id: str) -> str | None:
        """The practitioner who holds this device id in the bound tenant, whether it is revoked or
        not, or None. Another tenant's device is None (R11: the edge names a device, never a
        person)."""
        ...

    async def mark_verified(self, practitioner_id: str, device_id: str, at: datetime) -> None:
        """Record that a text code was verified for this practitioner's device at `at` (U32: the
        30-day check and the 10 minutes in which a PIN may be set both read it). A device that is
        not registered, or is revoked, or is another practitioner's, is left alone."""
        ...

    async def verified_at(self, practitioner_id: str, device_id: str) -> datetime | None:
        """When a text code was last verified for this practitioner's device, or None: never
        verified, not registered, revoked, or another practitioner's device."""
        ...

    async def get(self, device_id: str) -> Device | None:
        """The wall screen of the bound tenant with this id, or None. Takes the screen's write lock
        first, so a read that decides a single-use change cannot interleave with another (L85): use
        it inside the unit of work that saves. A device of another tenant is None."""
        ...

    async def save(self, device: Device) -> None:
        """Create or replace the wall screen of the bound tenant with this id. A device id that
        another tenant or a practitioner's device already holds is Conflict."""
        ...

    async def peek(self, device_id: str) -> Device | None:
        """`get` without the write lock, for reads that decide nothing single-use (TEN-067: a wall
        screen asks for its board setting on every refresh). Another tenant's screen is None."""
        ...

    async def list_screens(self) -> list[Device]:
        """Every wall screen of the bound tenant, any status, by name then id (W9I). A
        practitioner's device is never one, and another tenant's screen is never listed. Takes no
        lock."""
        ...

    async def confirm_active(
        self, device_id: str, seen_at: datetime, refresh_after: timedelta
    ) -> bool:
        """True when the bound tenant holds an ACTIVE wall screen with this id (W9I: the edge asks
        this of every wall request, so a revoked screen is refused at once). When it is, and its
        last seen time is absent or older than `seen_at - refresh_after`, the time is set to
        `seen_at` in the same step; a screen seen more recently is not written. A revoked, waiting,
        unknown or another tenant's screen is False and nothing is written."""
        ...

    async def find_by_token_hash(self, token_hash: str) -> Device | None:
        """The ACTIVE wall screen of the bound tenant whose token hashes to this, or None: a screen
        that is not active, or of another tenant, is never found. More than one is Conflict."""
        ...
