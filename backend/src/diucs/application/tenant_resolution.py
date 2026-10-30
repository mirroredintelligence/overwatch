"""Pre-session resolution (TEN-041, DEC-520). Stub for the red commit."""

from collections.abc import Collection
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.tenant_lines import InboundLine
from diucs.application.ports.outbound.tenants import TenantDirectory
from diucs.application.ports.outbound.tokens import SecretStore
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.domain.errors import NotFound
from diucs.domain.model.device import Device
from diucs.domain.rules.tokens import LinkCheck, LinkTokenRecord

ENTRY_REFUSED_MESSAGE: Final = ""


class EntryKind(StrEnum):
    LINK = "link"


class EntryRefused(NotFound):
    pass


@dataclass(frozen=True, slots=True)
class ResolvedLink:
    record: LinkTokenRecord
    state: LinkCheck


class DirectoryInboundLines:
    def __init__(self, directory: TenantDirectory) -> None:
        raise NotImplementedError

    async def for_number(self, to_number: str, account_sid: str) -> InboundLine | None:
        raise NotImplementedError

    async def for_account(self, account_sid: str) -> InboundLine | None:
        raise NotImplementedError


class PreSessionResolver:
    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock, secrets: SecretStore) -> None:
        raise NotImplementedError

    async def link(self, token: str, purposes: Collection[str]) -> ResolvedLink:
        raise NotImplementedError

    async def open_link(self, token: str, purposes: Collection[str]) -> ResolvedLink:
        raise NotImplementedError

    async def invitation(self, token: str) -> ResolvedLink:
        raise NotImplementedError

    async def device(self, token: str) -> Device:
        raise NotImplementedError
