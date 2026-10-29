"""Process entry for the inbound queue workers (I08). Stub."""

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

from diucs.adapters.inbound.workers.outbox_relay import StaticTenants
from diucs.adapters.inbound.workers.servicebus_runner import ServiceBusRunner
from diucs.bootstrap.settings import Settings

TENANTS_VARIABLE = "DIUCS_WORKER_TENANTS"


class WorkersConfigError(Exception):
    pass


def configured_tenants(environ: Mapping[str, str]) -> StaticTenants:
    return StaticTenants([])


def service_bus_connection(settings: Settings) -> str:
    return ""


def build_runners(
    client: Any, handle_inbound_text: Any, uow_factory: Any, tenants: Any
) -> list[ServiceBusRunner]:
    return []


async def run_workers(runners: Sequence[ServiceBusRunner], stop: asyncio.Event) -> None:
    return None


async def _run(settings: Settings, tenants: StaticTenants) -> None:
    return None


def main() -> None:
    return None
