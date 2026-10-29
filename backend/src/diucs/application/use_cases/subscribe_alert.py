"""SaveAlertPreferences and GetAlertPreferences (U33). Stub: the behaviour is written in the
implement step."""

from dataclasses import dataclass
from datetime import UTC, datetime, time
from typing import Final

from diucs.application.actor import Actor
from diucs.domain.codes import AlertKind

NEVER_SAVED: Final = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class SaveAlertPreferencesCommand:
    idempotency_key: str
    actor: Actor
    kinds: frozenset[AlertKind]
    not_updated_hours: int
    quiet_hours: tuple[time, time] | None
    quiet_critical_only: bool
    ack_minutes: int
    deputy_id: str | None
    daily_summary: bool
    weekly_summary: bool


class SaveAlertPreferences:
    def __init__(self, uow_factory: object, idempotency: object, clock: object) -> None:
        raise NotImplementedError

    async def execute(self, command: SaveAlertPreferencesCommand) -> object:
        raise NotImplementedError


class GetAlertPreferences:
    def __init__(self, uow_factory: object) -> None:
        raise NotImplementedError

    async def execute(self, actor: Actor) -> object:
        raise NotImplementedError
