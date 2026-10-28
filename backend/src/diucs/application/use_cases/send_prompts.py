"""SendPrompts (U03, DEC-115). Round-2 red stub (DEC-010): names and signatures only."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from diucs.application.actor import Actor
from diucs.application.idempotency import IdempotencyStore
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.tokens import (
    LinkTokenRepository,
    LinkTokenService,
    SecretStore,
)
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory

SKIP_INACTIVE: Final = "the service is not active"
SKIP_SUSPENDED: Final = "the service is suspended"
SKIP_OUT_OF_HOURS: Final = "the service is out of hours at the due time"
SKIP_REPLY_WINDOW: Final = "the reply window for this prompt has already closed"
SKIP_NO_WINDOW: Final = "the unit label has no readable window, so the first prompt is not sent"
SKIP_NO_REPORTER: Final = "no reporter can be texted for this service"

LinkTokenServiceFactory = Callable[[LinkTokenRepository], LinkTokenService]


def seal_content(content: str, secret: bytes) -> str:
    raise NotImplementedError


def unseal_content(sealed: str, secret: bytes) -> str:
    raise NotImplementedError


@dataclass(frozen=True, slots=True)
class SendPromptCommand:
    idempotency_key: str
    actor: Actor
    service_id: str
    due_at: datetime


@dataclass(frozen=True, slots=True)
class SendPromptResult:
    sent: bool
    communication_ids: tuple[str, ...]
    skipped_reason: str | None
    replayed: bool = False


class SendPrompts:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        ids: IdGenerator,
        idempotency: IdempotencyStore,
        link_tokens: LinkTokenServiceFactory,
        link_base_url: str,
        secret_store: SecretStore,
    ) -> None:
        self._uow_factory = uow_factory

    async def execute(self, command: SendPromptCommand) -> SendPromptResult:
        return SendPromptResult(sent=False, communication_ids=(), skipped_reason="stub")
