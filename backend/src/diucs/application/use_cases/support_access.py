"""Consent-based support access (O06). Stub for the red commit."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CreateSupportCodeCommand:
    actor: Any
    session_id: str
    device_type: str
    app_mode: str
    release: str


@dataclass(frozen=True, slots=True)
class CreateSupportCodeResult:
    code: str
    expires_at: Any


@dataclass(frozen=True, slots=True)
class StopSharingCommand:
    actor: Any
    session_id: str


@dataclass(frozen=True, slots=True)
class OpenSessionCommand:
    actor: Any
    code: str | None = None
    session_id: str | None = None
    ticket: str | None = None
    approved_by: str | None = None


@dataclass(frozen=True, slots=True)
class OpenSessionResult:
    access_id: str
    session_id: str
    expires_at: Any


@dataclass(frozen=True, slots=True)
class ListMyAccessesCommand:
    actor: Any
    session_id: str


@dataclass(frozen=True, slots=True)
class AccessView:
    opened_at: Any
    expires_at: Any
    by: str


class CreateSupportCode:
    def __init__(self, uow_factory: Any, clock: Any, ids: Any, secrets: Any) -> None:
        raise NotImplementedError

    async def execute(self, command: CreateSupportCodeCommand) -> CreateSupportCodeResult:
        raise NotImplementedError


class StopSharing:
    def __init__(self, uow_factory: Any, clock: Any) -> None:
        raise NotImplementedError

    async def execute(self, command: StopSharingCommand) -> int:
        raise NotImplementedError


class OpenSessionForSupport:
    def __init__(self, uow_factory: Any, clock: Any, ids: Any, secrets: Any) -> None:
        raise NotImplementedError

    async def execute(self, command: OpenSessionCommand) -> OpenSessionResult:
        raise NotImplementedError


class ListMyAccesses:
    def __init__(self, uow_factory: Any, clock: Any) -> None:
        raise NotImplementedError

    async def execute(self, command: ListMyAccessesCommand) -> list[AccessView]:
        raise NotImplementedError
