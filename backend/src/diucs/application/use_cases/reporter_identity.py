"""Reporter identity at the edge (R11): the use cases the identity routes run. Stub for the red
commit."""

from dataclasses import dataclass
from enum import StrEnum

from diucs.application.actor import Actor
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.identity import SessionStore
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.pin import PinSignIn, SetPin
from diucs.application.use_cases.remove_person import StartNewPhone
from diucs.application.use_cases.text_code import VerifyTextCode
from diucs.domain.codes import Role

UNKNOWN_PREFIX = "unknown-"


def unknown_person(device_id: str) -> str:
    raise NotImplementedError


@dataclass(frozen=True, slots=True)
class ConfirmDeviceCommand:
    phone: str
    code: str
    purpose: str
    device_id: str


@dataclass(frozen=True, slots=True)
class ConfirmDeviceResult:
    verified: bool
    tries_left: int
    needs_new_code: bool
    device_refused: bool
    awaiting_callback: bool


class ConfirmDeviceByTextCode:
    def __init__(
        self,
        verify: VerifyTextCode,
        record: object,
        start: StartNewPhone,
        clock: Clock,
    ) -> None:
        self._verify = verify

    async def execute(self, command: ConfirmDeviceCommand) -> ConfirmDeviceResult:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class SetDevicePinCommand:
    device_id: str
    pin: str


class SetDevicePin:
    def __init__(self, uow_factory: UnitOfWorkFactory, set_pin: SetPin) -> None:
        self._uow_factory = uow_factory

    async def execute(self, command: SetDevicePinCommand) -> bool:
        raise NotImplementedError


class SignInKind(StrEnum):
    SIGNED_IN = "signed-in"
    WRONG_PIN = "wrong-pin"
    LOCKED = "locked"
    NEEDS_TEXT_CODE = "needs-text-code"


@dataclass(frozen=True, slots=True)
class ReporterSignInCommand:
    device_id: str
    pin: str


@dataclass(frozen=True, slots=True)
class ReporterSignInResult:
    kind: SignInKind
    tries_left: int
    session_id: str | None
    role: Role | None
    service_ids: tuple[str, ...]


class ReporterSignIn:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        pin_sign_in: PinSignIn,
        sessions: SessionStore,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory

    async def execute(self, command: ReporterSignInCommand) -> ReporterSignInResult:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class ReverifyStatusResult:
    reverify_due: bool
    days_left: int


class ReverifyStatus:
    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory

    async def execute(self, device_id: str) -> ReverifyStatusResult:
        raise NotImplementedError


class CheckReporterAccess:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def execute(self, actor: Actor) -> bool:
        raise NotImplementedError
