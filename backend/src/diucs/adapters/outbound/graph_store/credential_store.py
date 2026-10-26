"""Neo4j stores for PIN credentials and devices (P16). Stub for the red commit (DEC-010)."""

from datetime import datetime

from neo4j import AsyncManagedTransaction

from diucs.domain.rules.identity_policy import PinState


class Neo4jPinStore:
    def __init__(self, tx: AsyncManagedTransaction) -> None:
        self._tx = tx

    async def set_pin(self, practitioner_id: str, device_id: str, pin_hash: str) -> None:
        raise NotImplementedError

    async def get(self, practitioner_id: str, device_id: str) -> tuple[str, PinState] | None:
        raise NotImplementedError

    async def save_state(self, practitioner_id: str, device_id: str, state: PinState) -> None:
        raise NotImplementedError

    async def clear_all(self, practitioner_id: str) -> None:
        raise NotImplementedError


class Neo4jDeviceRegistry:
    def __init__(self, tx: AsyncManagedTransaction) -> None:
        self._tx = tx

    async def register(self, practitioner_id: str, device_id: str, at: datetime) -> None:
        raise NotImplementedError

    async def known(self, practitioner_id: str, device_id: str) -> bool:
        raise NotImplementedError

    async def revoke_all(self, practitioner_id: str) -> None:
        raise NotImplementedError
