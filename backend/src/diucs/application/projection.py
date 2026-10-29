"""Rows, bodies and the statement check for the network projection (TEN-052). Stub."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any

from diucs.domain.model.network import GrantScope
from diucs.domain.rules.projection import (
    CapacityProjection,
    CriteriaProjection,
    OpeningHourProjection,
    ServiceProjection,
)

type ProjectionValue = str | int | float | bool | None | tuple[str, ...]
type Projection = ServiceProjection | CapacityProjection | CriteriaProjection
type RowValue = str | int | float | bool | None | list[Any] | datetime | date | time


@dataclass(frozen=True, slots=True)
class ProjectionRow:
    label: str
    params: Mapping[str, RowValue]


def to_rows(dto: Projection) -> list[ProjectionRow]:
    raise NotImplementedError


def to_body(dto: Projection) -> dict[str, ProjectionValue]:
    raise NotImplementedError


def from_body(kind: GrantScope, body: Mapping[str, object]) -> Projection:
    raise NotImplementedError


def body_keys(kind: GrantScope) -> frozenset[str]:
    raise NotImplementedError


def format_window(hour: OpeningHourProjection) -> str:
    raise NotImplementedError


def parse_window(text: str, position: int) -> OpeningHourProjection:
    raise NotImplementedError


def check_network_write_statement(cypher: str) -> list[str]:
    raise NotImplementedError


def assert_network_write_statement(cypher: str) -> None:
    raise NotImplementedError
