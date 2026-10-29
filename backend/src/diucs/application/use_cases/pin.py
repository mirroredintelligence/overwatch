"""STUB (U32 red): declarations only."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final

from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.identity import RateLimiter
from diucs.application.ports.outbound.tokens import SecretStore
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.domain.codes import PractitionerRoleCode, Role
from diucs.domain.errors import DomainError
from diucs.domain.model.people import PractitionerRole

PIN_HMAC_SECRET: Final = "pin-hmac"
PIN_SET_WINDOW: Final = timedelta(minutes=10)
VERIFIED_PURPOSES: Final = frozenset[str]()
RATE_WINDOW: Final = timedelta(minutes=10)
SIGN_IN_PER_DEVICE: Final = 0
SIGN_IN_PER_PERSON: Final = 0
SET_PIN_PER_PERSON: Final = 0
RATE_LIMITED_MESSAGE: Final = ""


class PinRateLimited(DomainError):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(RATE_LIMITED_MESSAGE)
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True, slots=True)
class SetPinCommand:
    practitioner_id: str
    device_id: str
    pin: str = field(repr=False)
    verified_at: datetime


@dataclass(frozen=True, slots=True)
class SetPinResult:
    ok: bool


@dataclass(frozen=True, slots=True)
class PinSignInCommand:
    practitioner_id: str
    device_id: str
    pin: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class PinSignInResult:
    ok: bool
    locked: bool
    tries_left: int
    needs_text_code: bool
    practitioner_id: str | None
    role: Role | None
    service_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RecordTextCodeVerifiedCommand:
    practitioner_id: str
    device_id: str
    verified_at: datetime
    purpose: str


@dataclass(frozen=True, slots=True)
class RecordTextCodeVerifiedResult:
    device_known: bool


def pin_hash(secret: bytes, practitioner_id: str, device_id: str, pin: str) -> str:
    raise NotImplementedError


def verification_is_fresh(stored: datetime | None, claimed: datetime, now: datetime) -> bool:
    raise NotImplementedError


def session_role(codes: list[PractitionerRoleCode]) -> Role | None:
    raise NotImplementedError


def reporter_service_ids(roles: list[PractitionerRole], now: datetime) -> tuple[str, ...]:
    raise NotImplementedError


def limiter_key(kind: str, *parts: str) -> str:
    raise NotImplementedError


class SetPin:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        secret_store: SecretStore,
        clock: Clock,
        rate_limiter: RateLimiter,
    ) -> None:
        raise NotImplementedError

    async def execute(self, command: SetPinCommand) -> SetPinResult:
        raise NotImplementedError


class PinSignIn:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        secret_store: SecretStore,
        clock: Clock,
        rate_limiter: RateLimiter,
    ) -> None:
        raise NotImplementedError

    async def execute(self, command: PinSignInCommand) -> PinSignInResult:
        raise NotImplementedError


class RecordTextCodeVerified:
    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        raise NotImplementedError

    async def execute(
        self, command: RecordTextCodeVerifiedCommand
    ) -> RecordTextCodeVerifiedResult:
        raise NotImplementedError
