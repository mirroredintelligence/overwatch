"""Moving services between phones (U38). Stub: the behaviour is written in the implement step."""

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol

from diucs.application.actor import Actor

MOVE_CODE_PURPOSE: Final = "setup"


class CodeVerifier(Protocol):
    async def verify(self, phone: str, purpose: str, code: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class StartServiceMoveCommand:
    actor: Actor
    service_id: str
    to_mobile: str
    until: datetime | None


@dataclass(frozen=True, slots=True)
class MoveResult:
    move_id: str


class StartServiceMove:
    def __init__(self, uow_factory: object, ids: object, clock: object, hasher: object) -> None:
        raise NotImplementedError

    async def execute(self, command: StartServiceMoveCommand) -> MoveResult:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class VerifyServiceMoveCodeCommand:
    move_id: str
    mobile: str
    """The new number again: a move stores only its hash, and the code is texted to the number."""
    code: str


@dataclass(frozen=True, slots=True)
class RecordMoveCallBackCommand:
    actor: Actor
    move_id: str


@dataclass(frozen=True, slots=True)
class CompleteServiceMoveCommand:
    actor: Actor
    move_id: str


@dataclass(frozen=True, slots=True)
class AddServiceToPhoneCommand:
    actor: Actor
    service_id: str
    mobile: str


@dataclass(frozen=True, slots=True)
class AddServiceToPhoneResult:
    role_id: str


@dataclass(frozen=True, slots=True)
class AnswerServiceAdditionCommand:
    actor: Actor
    role_id: str
    accept: bool


class VerifyServiceMoveCode:
    def __init__(self, uow_factory: object, verifier: object, clock: object) -> None:
        raise NotImplementedError

    async def execute(self, command: VerifyServiceMoveCodeCommand) -> None:
        raise NotImplementedError


class RecordMoveCallBack:
    def __init__(self, uow_factory: object, clock: object) -> None:
        raise NotImplementedError

    async def execute(self, command: RecordMoveCallBackCommand) -> None:
        raise NotImplementedError


class CompleteServiceMove:
    def __init__(self, uow_factory: object, ids: object, clock: object, hasher: object) -> None:
        raise NotImplementedError

    async def execute(self, command: CompleteServiceMoveCommand) -> None:
        raise NotImplementedError


class AddServiceToPhone:
    def __init__(self, uow_factory: object, ids: object, clock: object, hasher: object) -> None:
        raise NotImplementedError

    async def execute(self, command: AddServiceToPhoneCommand) -> AddServiceToPhoneResult:
        raise NotImplementedError


class AnswerServiceAddition:
    def __init__(self, uow_factory: object, clock: object) -> None:
        raise NotImplementedError

    async def execute(self, command: AnswerServiceAdditionCommand) -> None:
        raise NotImplementedError
