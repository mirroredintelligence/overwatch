"""The relationship matrix of the cross-tenant reference test (TEN-029). Stub for the red commit."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class Handling(StrEnum):
    CHECKED = "checked"
    PLACEHOLDER = "placeholder"
    TENANT_LOCAL = "tenant-local"
    SHARED = "shared"
    REGISTRY = "registry"


@dataclass(frozen=True, slots=True)
class Relationship:
    type: str
    handling: Handling
    literal: bool = True
    cases: tuple[str, ...] = ()
    note: str = ""


RELATIONSHIPS: tuple[Relationship, ...] = ()


def written_types(root: Path | None = None) -> frozenset[str]:
    raise NotImplementedError


def checked_cases() -> dict[str, str]:
    raise NotImplementedError


def shape(error: Exception, *ids: str) -> str:
    raise NotImplementedError
