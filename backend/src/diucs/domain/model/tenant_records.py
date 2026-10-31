"""A tenant's configuration records besides its versions (TEN-026).

A tenant's channels (the Twilio subaccount that carries its texts and the sender of its email), its
retention rules, the directory it signs in through and the groups mapped to its roles. Rules: audit
F section 2.3 (the records), DEC-131 (a secret is a reference and never a value), DEC-136 item 10
(retention is set before activation), DEC-155 (fail closed). The contacts, the configuration
versions and the settings are in `tenant.py` and `rules/tenant_settings.py` (TEN-006).

Pure: no I/O and no clock. An enum is checked by exact type (lessons L3 and L38: `"active"` and the
`active` member of another enum equal each other), a datetime must be timezone-aware, and no
refusal repeats a value, so no sender, address, secret reference, directory or group ever reaches
an error message. The text of a channel is checked by the privacy guard (D17) like every other
tenant text.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from diucs.domain.codes import Role
from diucs.domain.errors import ValidationFailed
from diucs.domain.messages.privacy_guard import find_patient_data
from diucs.domain.model.tenant import NumberStatus, RetentionClass

WRONG_TYPE_MESSAGE: Final = "has the wrong type"
TEXT_MESSAGE: Final = "must be plain text of the right length"
SHAPE_MESSAGE: Final = "is not the right shape"
TOGETHER_MESSAGE: Final = "does not agree with the other fields of the record"

# ---------------------------------------------------------------- enums


class ChannelKind(StrEnum):
    SMS = "sms"
    EMAIL = "email"


class ChannelProvider(StrEnum):
    TWILIO = "twilio"
    SMTP = "smtp"


class RetentionAction(StrEnum):
    DELETE = "delete"
    SUMMARISE = "summarise"
    KEEP = "keep"


class BindingStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    REVOKED = "revoked"


class MappingStatus(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"


# The provider each kind of channel uses (audit F 2.3).
CHANNEL_PROVIDER: Final = MappingProxyType(
    {ChannelKind.SMS: ChannelProvider.TWILIO, ChannelKind.EMAIL: ChannelProvider.SMTP}
)

# The roles a directory group may be mapped to: the staff roles, and the network administrator.
# A wall screen, an anonymous link and a reporter's own device do not sign in through the directory,
# and `support` is a platform role that comes from the operator directory (DEC-134 item 5), never
# from a customer's. The tenant administrator is not mappable: that role comes from the first
# administrator's invitation (DEC-1007 item 4). The network administrator is a role of the network
# owner's own directory (TEN-080, DEC-1260): a mapping on any other tenant is stored but gives
# nothing, because the token exchange gives the role only to a tenant that owns an active network.
ENTRA_MAPPABLE_ROLES: Final = frozenset(
    {
        Role.ADVISOR,
        Role.CLINICAL,
        Role.LEAD,
        Role.OWNER,
        Role.EXEC,
        Role.AUDIT,
        Role.NETWORK_ADMIN,
    }
)

# Retention (DEC-136 item 10, audit F 2.3). The audit chain and the safety concerns are kept until
# the tenant is purged; every other class is deleted or summarised after a number of days.
KEPT_UNTIL_PURGE: Final = frozenset({RetentionClass.AUDIT_CHAIN, RetentionClass.SAFETY_CONCERNS})
MAX_KEEP_DAYS: Final = 3650  # [ASSUMED] ten years

CHANNEL_ID_PATTERN: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
ACCOUNT_SID_PATTERN: Final = re.compile(r"AC[0-9a-f]{32}")
# `<kind>/<tenant id>/<name>`: the shape of `application/ports/outbound/tenants.py::secret_ref`. The
# domain checks the shape only; that the tenant part is the record's own tenant is checked where
# the tenant is known (the use case, through `check_secret_ref`).
SECRET_REF_PATTERN: Final = re.compile(
    r"[a-z][a-z0-9-]{0,31}/[a-z0-9][a-z0-9-]{1,30}/[a-z0-9][a-z0-9._-]{0,63}"
)
EMAIL_PATTERN: Final = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
DIRECTORY_ID_PATTERN: Final = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
REFERENCE_PATTERN: Final = re.compile(r"[A-Za-z0-9 ._:/-]+")
REFERENCE_MAX_LENGTH: Final = 80
SENDER_LABEL_MAX_LENGTH: Final = 40
DISPLAY_NAME_MAX_LENGTH: Final = 60
ADDRESS_MAX_LENGTH: Final = 254
FORBIDDEN_CHARACTERS: Final = frozenset("{}<>")

# ---------------------------------------------------------------- field checks


def _enum(field: str, value: object, enum_type: type[StrEnum]) -> None:
    if type(value) is not enum_type:
        raise ValidationFailed(field, WRONG_TYPE_MESSAGE)


def _text(field: str, value: object, maximum: int) -> None:
    if (
        type(value) is not str
        or not 1 <= len(value) <= maximum
        or value != value.strip()
        or not value.isprintable()
        or any(character in FORBIDDEN_CHARACTERS for character in value)
        or find_patient_data(value)
    ):
        raise ValidationFailed(field, TEXT_MESSAGE)


def _optional_text(field: str, value: object, maximum: int) -> None:
    if value is not None:
        _text(field, value, maximum)


def _matches(field: str, value: object, pattern: re.Pattern[str]) -> None:
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise ValidationFailed(field, SHAPE_MESSAGE)


def _reference(field: str, value: object) -> None:
    if (
        type(value) is not str
        or len(value) > REFERENCE_MAX_LENGTH
        or REFERENCE_PATTERN.fullmatch(value) is None
        or value != value.strip()
    ):
        raise ValidationFailed(field, SHAPE_MESSAGE)


def _aware(field: str, value: object) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValidationFailed(field, "must be a timezone-aware datetime")


# ---------------------------------------------------------------- channels


@dataclass(frozen=True, slots=True, kw_only=True)
class TenantChannel:
    """A way a tenant's messages leave: a Twilio subaccount for text or an address for email.

    The auth token and any password are never a field: `secret_ref` is the reference of the secret
    in the secret store (DEC-131 item 4). A text channel holds the account SID (an identifier, not
    a secret) and the reference of its token; an email channel holds the sender address and, when
    it needs one, the reference of its SMTP secret."""

    id: str
    kind: ChannelKind
    provider: ChannelProvider
    status: NumberStatus
    sender_label: str
    account_sid: str | None = None
    secret_ref: str | None = None
    from_address: str | None = None
    from_display_name: str | None = None

    def __post_init__(self) -> None:
        _matches("id", self.id, CHANNEL_ID_PATTERN)
        _enum("kind", self.kind, ChannelKind)
        _enum("provider", self.provider, ChannelProvider)
        _enum("status", self.status, NumberStatus)
        if self.provider is not CHANNEL_PROVIDER[self.kind]:
            raise ValidationFailed("provider", TOGETHER_MESSAGE)
        _text("sender_label", self.sender_label, SENDER_LABEL_MAX_LENGTH)
        if self.secret_ref is not None:
            _matches("secret_ref", self.secret_ref, SECRET_REF_PATTERN)
        if self.kind is ChannelKind.SMS:
            self._check_text_channel()
        else:
            self._check_email_channel()

    def _check_text_channel(self) -> None:
        if self.account_sid is None or self.secret_ref is None:
            raise ValidationFailed("account_sid", TOGETHER_MESSAGE)
        _matches("account_sid", self.account_sid, ACCOUNT_SID_PATTERN)
        if self.from_address is not None or self.from_display_name is not None:
            raise ValidationFailed("from_address", TOGETHER_MESSAGE)

    def _check_email_channel(self) -> None:
        if self.from_address is None or self.account_sid is not None:
            raise ValidationFailed("from_address", TOGETHER_MESSAGE)
        _text("from_address", self.from_address, ADDRESS_MAX_LENGTH)
        _matches("from_address", self.from_address, EMAIL_PATTERN)
        _optional_text("from_display_name", self.from_display_name, DISPLAY_NAME_MAX_LENGTH)


# ---------------------------------------------------------------- retention


@dataclass(frozen=True, slots=True)
class TenantRetention:
    """How long a class of data is kept. `keep_days` is `None` for a class that is kept until the
    tenant is purged (`KEEP`) and a whole number of days, 1 to `MAX_KEEP_DAYS`, for the rest."""

    data_class: RetentionClass
    keep_days: int | None
    action: RetentionAction

    def __post_init__(self) -> None:
        _enum("data_class", self.data_class, RetentionClass)
        _enum("action", self.action, RetentionAction)
        kept = self.data_class in KEPT_UNTIL_PURGE
        if kept != (self.action is RetentionAction.KEEP):
            raise ValidationFailed("action", TOGETHER_MESSAGE)
        if kept:
            if self.keep_days is not None:
                raise ValidationFailed("keep_days", TOGETHER_MESSAGE)
        elif (
            type(self.keep_days) is not int
            or isinstance(self.keep_days, bool)
            or not 1 <= self.keep_days <= MAX_KEEP_DAYS
        ):
            raise ValidationFailed("keep_days", "is outside the allowed range")


# [ASSUMED] (DEC-271), in the order of `RetentionClass`. The postcode and needs of a case are
# cleared at close by the rule book (domain-rules 3.2) whatever the case-audit row says: that row
# governs the kept fields (category, age band, urgency, scores, destination, outcome, times).
_DEFAULT_RETENTION: Final = (
    TenantRetention(RetentionClass.CAPACITY_REPORTS, 730, RetentionAction.SUMMARISE),
    TenantRetention(RetentionClass.BOOKINGS, 730, RetentionAction.DELETE),
    TenantRetention(RetentionClass.CASE_AUDIT, 2555, RetentionAction.DELETE),
    TenantRetention(RetentionClass.COMMUNICATIONS, 730, RetentionAction.DELETE),
    TenantRetention(RetentionClass.TELEMETRY_RAW, 90, RetentionAction.DELETE),
    TenantRetention(RetentionClass.TELEMETRY_AGGREGATES, 730, RetentionAction.DELETE),
    TenantRetention(RetentionClass.AUDIT_CHAIN, None, RetentionAction.KEEP),
    TenantRetention(RetentionClass.SAFETY_CONCERNS, None, RetentionAction.KEEP),
)


def default_retention() -> tuple[TenantRetention, ...]:
    """The proposed schedule, one rule per class. It is a proposal: activation needs the rules to
    be set (stored), and setting the defaults is an explicit act of the administrator."""
    return _DEFAULT_RETENTION


# ---------------------------------------------------------------- the directory


@dataclass(frozen=True, slots=True)
class EntraBinding:
    """The directory a tenant's staff sign in through. It is `pending` until the platform operator
    has verified the domain, and then names when and by whom (audit F 2.3)."""

    directory_id: str
    status: BindingStatus
    verified_at: datetime | None = None
    verified_by_ref: str | None = None

    def __post_init__(self) -> None:
        _matches("directory_id", self.directory_id, DIRECTORY_ID_PATTERN)
        _enum("status", self.status, BindingStatus)
        verified = self.status is BindingStatus.VERIFIED
        if verified != (self.verified_at is not None) or verified != (
            self.verified_by_ref is not None
        ):
            raise ValidationFailed("verified_at", TOGETHER_MESSAGE)
        if verified:
            _aware("verified_at", self.verified_at)
            _reference("verified_by_ref", self.verified_by_ref)


@dataclass(frozen=True, slots=True)
class RoleMapping:
    """A directory group and the tenant role it gives. Replaces reading roles from a token claim."""

    group_object_id: str
    role: Role
    status: MappingStatus

    def __post_init__(self) -> None:
        _matches("group_object_id", self.group_object_id, DIRECTORY_ID_PATTERN)
        _enum("role", self.role, Role)
        if self.role not in ENTRA_MAPPABLE_ROLES:
            raise ValidationFailed("role", "is not a role a directory group may give")
        _enum("status", self.status, MappingStatus)
