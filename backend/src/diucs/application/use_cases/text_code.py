"""Text codes for registration, reporter set-up and re-verification (U25).

STUB (red commit): the names exist so the unit tests fail on their assertions. The build follows in
the next commit.
"""

import random
from dataclasses import dataclass
from datetime import datetime

from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.identity import CodeSender, CodeStore, PhoneHasher
from diucs.application.ports.outbound.tokens import SecretStore
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory


@dataclass(frozen=True, slots=True)
class RequestTextCodeCommand:
    idempotency_key: str
    phone: str
    purpose: str


@dataclass(frozen=True, slots=True)
class RequestTextCodeResult:
    sent: bool
    retry_after_seconds: int


@dataclass(frozen=True, slots=True)
class VerifyTextCodeCommand:
    phone: str
    purpose: str
    code: str


@dataclass(frozen=True, slots=True)
class VerifyTextCodeResult:
    ok: bool
    tries_left: int
    needs_new_code: bool
    practitioner_id: str | None
    invitation_id: str | None
    verified_at: datetime | None


def check_purpose(purpose: str) -> str:
    raise NotImplementedError


def code_key(phone_hash: str, purpose: str) -> str:
    raise NotImplementedError


def new_code(rng: random.Random) -> str:
    raise NotImplementedError


def code_hash(secret: bytes, phone_hash: str, purpose: str, code: str) -> str:
    raise NotImplementedError


def cooldown_seconds(last_sent_at: datetime, now: datetime) -> int:
    raise NotImplementedError


class RequestTextCode:
    def __init__(
        self,
        code_store: CodeStore,
        code_sender: CodeSender,
        phone_hasher: PhoneHasher,
        uow_factory: UnitOfWorkFactory,
        secret_store: SecretStore,
        clock: Clock,
        rng: random.Random,
    ) -> None:
        raise NotImplementedError

    async def execute(self, command: RequestTextCodeCommand) -> RequestTextCodeResult:
        raise NotImplementedError


class VerifyTextCode:
    def __init__(
        self,
        code_store: CodeStore,
        phone_hasher: PhoneHasher,
        uow_factory: UnitOfWorkFactory,
        secret_store: SecretStore,
        clock: Clock,
    ) -> None:
        raise NotImplementedError

    async def execute(self, command: VerifyTextCodeCommand) -> VerifyTextCodeResult:
        raise NotImplementedError
