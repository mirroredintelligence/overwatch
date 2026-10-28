"""SendPrompts (U03). Stub for the red commit (DEC-010)."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from diucs.application.actor import Actor
from diucs.application.idempotency import IdempotencyStore
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.tokens import LinkTokenRepository, LinkTokenService
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory

LinkTokenServiceFactory = Callable[[LinkTokenRepository], LinkTokenService]


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
    ) -> None:
        self._link_base_url = link_base_url

    async def execute(self, command: SendPromptCommand) -> SendPromptResult:
        return SendPromptResult(sent=False, communication_ids=(), skipped_reason="stub")
