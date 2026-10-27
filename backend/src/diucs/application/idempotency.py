"""Command replay: the stored first result of each command key (P15, DEC-090).

Stub for the red commit (DEC-010): constant returns only, no behaviour. Each returns a value that
no test expects, so every test fails on its own assertion line.
"""

from datetime import datetime
from typing import Protocol

_STUB = object()


class IdempotencyStore(Protocol):
    async def get(self, key: str) -> object | None: ...

    async def put(self, key: str, result: object) -> None: ...


def encode_result(result: object) -> tuple[str, str]:
    return ("stub:stub", "stub")


def decode_result(type_name: str, json_text: str) -> object:
    return _STUB


def format_instant(value: datetime) -> str:
    return "stub"
