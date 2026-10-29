"""Process entry for the outbox relay (I03). Red-commit stub (DEC-010): names, no behaviour."""

import asyncio
from collections.abc import Mapping

from diucs.adapters.inbound.workers.outbox_relay import StaticTenants
from diucs.bootstrap.settings import Settings


class RelayConfigError(Exception):
    """The relay cannot start with this configuration. The text is fixed and holds no value."""


def configured_tenants(environ: Mapping[str, str]) -> StaticTenants:
    raise NotImplementedError


def service_bus_connection(settings: Settings) -> str:
    raise NotImplementedError


async def serve(settings: Settings, tenants: StaticTenants, stop: asyncio.Event) -> None:
    raise NotImplementedError


def main() -> None:
    raise NotImplementedError
