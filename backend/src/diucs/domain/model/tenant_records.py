"""A tenant's configuration records besides its versions (TEN-026). Stub for the red commit."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from diucs.domain.codes import Role
from diucs.domain.model.tenant import NumberStatus, RetentionClass


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


KEPT_UNTIL_PURGE: Final[frozenset[RetentionClass]] = frozenset()
MAX_KEEP_DAYS: Final = 0
ENTRA_MAPPABLE_ROLES: Final[frozenset[Role]] = frozenset()


@dataclass(frozen=True, slots=True, kw_only=True)
class TenantChannel:
    id: str
    kind: ChannelKind
    provider: ChannelProvider
    status: NumberStatus
    sender_label: str
    account_sid: str | None = None
    secret_ref: str | None = None
    from_address: str | None = None
    from_display_name: str | None = None


@dataclass(frozen=True, slots=True)
class TenantRetention:
    data_class: RetentionClass
    keep_days: int | None
    action: RetentionAction


def default_retention() -> tuple[TenantRetention, ...]:
    raise NotImplementedError


@dataclass(frozen=True, slots=True)
class EntraBinding:
    directory_id: str
    status: BindingStatus
    verified_at: datetime | None = None
    verified_by_ref: str | None = None


@dataclass(frozen=True, slots=True)
class RoleMapping:
    group_object_id: str
    role: Role
    status: MappingStatus
