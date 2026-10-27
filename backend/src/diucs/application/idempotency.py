"""Command replay: the stored first result of each command key (P15, DEC-089).

Stub for the red commit (DEC-010): the behaviour is not written yet.
"""

from datetime import datetime
from typing import Protocol


class IdempotencyStore(Protocol):
    async def get(self, key: str) -> object | None: ...

    async def put(self, key: str, result: object) -> None: ...


def encode_result(result: object) -> tuple[str, str]:
    raise NotImplementedError


def decode_result(type_name: str, json_text: str) -> object:
    raise NotImplementedError


def format_instant(value: datetime) -> str:
    raise NotImplementedError
