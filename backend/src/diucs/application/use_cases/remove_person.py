"""People-access use cases (U37): the lead removes a person, a person signs out of every phone, and
a reporter who lost a phone moves to a new one after a lead call-back. Stub for the red commit."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from diucs.application.actor import Actor
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.identity import SessionStore
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory


class RemovalReason(StrEnum):
    LEFT_SERVICE = "left-service"
    CHANGED_ROLE = "changed-role"
    LOST_PHONE = "lost-phone"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class RemovePersonCommand:
    idempotency_key: str
    actor: Actor
    practitioner_id: str
    reason: RemovalReason


@dataclass(frozen=True, slots=True)
class RemovePersonResult:
    roles_ended: int
    devices_revoked: int
    push_removed: int
    covers_released: int
    services_without_reporter: tuple[str, ...]
    services_covered: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SignOutEverywhereCommand:
    idempotency_key: str
    actor: Actor


@dataclass(frozen=True, slots=True)
class SignOutEverywhereResult:
    devices_signed_out: int


@dataclass(frozen=True, slots=True)
class StartNewPhoneCommand:
    practitioner_id: str
    device_id: str
    verified_at: datetime


@dataclass(frozen=True, slots=True)
class StartNewPhoneResult:
    started: bool
    devices_signed_out: int


@dataclass(frozen=True, slots=True)
class ConfirmNewPhoneCommand:
    idempotency_key: str
    actor: Actor
    practitioner_id: str


@dataclass(frozen=True, slots=True)
class ConfirmNewPhoneResult:
    confirmed: int


class RemovePerson:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        ids: IdGenerator,
        sessions: SessionStore,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids
        self._sessions = sessions

    async def execute(self, command: RemovePersonCommand) -> RemovePersonResult:
        raise NotImplementedError


class SignOutEverywhere:
    def __init__(
        self, uow_factory: UnitOfWorkFactory, clock: Clock, sessions: SessionStore
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._sessions = sessions

    async def execute(self, command: SignOutEverywhereCommand) -> SignOutEverywhereResult:
        raise NotImplementedError


class StartNewPhone:
    def __init__(
        self, uow_factory: UnitOfWorkFactory, clock: Clock, sessions: SessionStore
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._sessions = sessions

    async def execute(self, command: StartNewPhoneCommand) -> StartNewPhoneResult:
        raise NotImplementedError


class ConfirmNewPhone:
    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, command: ConfirmNewPhoneCommand) -> ConfirmNewPhoneResult:
        raise NotImplementedError
