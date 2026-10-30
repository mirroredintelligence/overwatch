"""Stand-ins for the two repositories a pre-session resolver reads (TEN-041), for tests that reach
no store: a link-token repository and a device registry that record the hashes they were asked for,
and a unit of work that holds them under a chosen scope. Not a store of records (DEC-004): each
holds only what the test hands it.
"""

from types import TracebackType
from typing import Self

from diucs.application.tenancy import ScopeId
from diucs.domain.model.device import Device
from diucs.domain.rules.tokens import LinkTokenRecord


class Links:
    def __init__(self, records: dict[str, LinkTokenRecord]) -> None:
        self._records = records
        self.asked: list[str] = []

    async def get_by_hash(self, token_hash: str) -> LinkTokenRecord | None:
        self.asked.append(token_hash)
        return self._records.get(token_hash)


class Devices:
    def __init__(self, devices: dict[str, Device | Exception]) -> None:
        self._devices = devices
        self.asked: list[str] = []

    async def find_by_token_hash(self, token_hash: str) -> Device | None:
        self.asked.append(token_hash)
        found = self._devices.get(token_hash)
        if isinstance(found, Exception):
            raise found
        return found


class Uow:
    def __init__(self, links: Links, devices: Devices, scope: ScopeId | None) -> None:
        self.link_tokens = links
        self.devices = devices
        self._scope = scope
        self.committed = False

    @property
    def unit_scope(self) -> ScopeId | None:
        return self._scope

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True
