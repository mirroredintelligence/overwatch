"""Stub (red commit)."""

from dataclasses import dataclass
from datetime import datetime

from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.network import NetworkRegistry
from diucs.application.ports.outbound.unit_of_work import NetworkUnitOfWorkFactory
from diucs.domain.model.network import GrantEndReason, GrantScope


@dataclass(frozen=True, slots=True)
class EndResult:
    sources_ended: int
    rows_marked: int
    skipped: bool = False


class EndProjections:
    def __init__(
        self, uow_factory: NetworkUnitOfWorkFactory, registry: NetworkRegistry, clock: Clock
    ) -> None:
        self._uow_factory = uow_factory

    async def end_grant(
        self,
        network_id: str,
        member_tenant_id: str,
        scope: GrantScope,
        *,
        reason: GrantEndReason,
        at: datetime,
    ) -> EndResult:
        raise NotImplementedError

    async def end_member(
        self, network_id: str, member_tenant_id: str, *, at: datetime
    ) -> EndResult:
        raise NotImplementedError
