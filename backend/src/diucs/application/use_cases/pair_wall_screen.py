"""PairWallScreen: pairing a wall display with a six-digit code (U10, DEC-160).

Stub for the red commit (DEC-010): the names and signatures only.
"""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Literal

from diucs.application.actor import Actor
from diucs.application.ports.outbound.cache import Cache
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.tokens import SecretStore
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.domain.errors import DomainError
from diucs.domain.model.device import BoardScope
from diucs.domain.rules.tokens import PAIRING_CODE_VALID_FOR

USE_CASE: Final = "PairWallScreen"
PAIRING_PURPOSE: Final = "wall-pairing"
PAIRING_SECRET_PURPOSE: Final = "wall-pairing-secret"
START_LIMIT: Final = 20
CONFIRM_FAILURE_LIMIT: Final = 5
LIMIT_WINDOW: Final = PAIRING_CODE_VALID_FOR
CODE_ATTEMPTS: Final = 10
REFUSED_MESSAGE: Final = "This code or screen is not valid."


class PairingRateLimited(DomainError):
    """Too many pairing attempts for now."""


@dataclass(frozen=True, slots=True)
class StartPairingResult:
    pairing_id: str
    code_display: str
    screen_secret: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ConfirmPairingCommand:
    idempotency_key: str
    actor: Actor
    code: str
    screen_name: str
    location: str | None
    board_scope: BoardScope = BoardScope.TENANT


@dataclass(frozen=True, slots=True)
class ConfirmPairingResult:
    device_id: str
    screen_name: str
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class ClaimPairingCommand:
    pairing_id: str
    screen_secret: str


@dataclass(frozen=True, slots=True)
class ClaimPairingResult:
    status: Literal["waiting", "paired", "expired"]
    device_token: str | None


def normalise_code(text: str) -> str | None:
    """The six digits of a typed code ("482 913", "482-913", "482913"), or None."""
    raise NotImplementedError


class AttemptLimiter:
    """A count of events inside a window, kept in the cache (nothing of record)."""

    def __init__(self, cache: Cache) -> None:
        self._cache = cache

    async def take(self, name: str, limit: int, window: timedelta) -> bool:
        raise NotImplementedError

    async def is_full(self, name: str, limit: int) -> bool:
        raise NotImplementedError


class StartPairing:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        ids: IdGenerator,
        rng: random.Random,
        secret_store: SecretStore,
        cache: Cache,
    ) -> None:
        self._uow_factory = uow_factory

    async def execute(self) -> StartPairingResult:
        raise NotImplementedError


class ConfirmPairing:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        secret_store: SecretStore,
        cache: Cache,
    ) -> None:
        self._uow_factory = uow_factory

    async def execute(self, command: ConfirmPairingCommand) -> ConfirmPairingResult:
        raise NotImplementedError


class ClaimPairing:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        rng: random.Random,
        secret_store: SecretStore,
    ) -> None:
        self._uow_factory = uow_factory

    async def execute(self, command: ClaimPairingCommand) -> ClaimPairingResult:
        raise NotImplementedError
