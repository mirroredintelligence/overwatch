"""STUB (U27 red): declarations only."""

from dataclasses import dataclass
from typing import Any, Protocol


class _Store(Protocol):
    async def put(self, resource: dict[str, Any], expected_version: str | None) -> str: ...

    async def get(self, type: str, id: str) -> dict[str, Any] | None: ...


@dataclass(frozen=True, slots=True)
class BundleEntry:
    method: str
    type: str
    id: str
    full_url: str
    resource: dict[str, Any]


def resolve_bundle(bundle: dict[str, Any]) -> list[BundleEntry]:
    raise NotImplementedError


async def write_bundle(store: _Store, bundle: dict[str, Any]) -> dict[str, str]:
    raise NotImplementedError
