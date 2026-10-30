"""Stub (red commit)."""

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.network import NetworkRegistry
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.network_leave import EndProjections
from diucs.application.use_cases.project_network import ProjectNetwork


class GovernanceOutcome(StrEnum):
    HANDLED = "handled"
    IGNORED = "ignored"
    SKIPPED = "skipped"


class NetworkGovernance:
    def __init__(
        self,
        registry: NetworkRegistry,
        ends: EndProjections,
        producer: ProjectNetwork,
        uow_factory: UnitOfWorkFactory,
        ids: IdGenerator,
        clock: Clock,
        active_tenants: Any,
    ) -> None:
        pass

    async def handle(
        self, event_type: str, payload: Mapping[str, Any], *, bus_tenant: str
    ) -> GovernanceOutcome:
        raise NotImplementedError
