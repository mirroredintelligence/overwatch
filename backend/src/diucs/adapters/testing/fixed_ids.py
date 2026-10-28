"""Test identifier generator that counts up: prefix-1, prefix-2, ..."""

from typing import Self

from diucs.application.tenancy import ScopeId


class SequentialIds:
    def __init__(self, prefix: str = "id") -> None:
        self._prefix = prefix
        self._count = 0

    @classmethod
    def scoped(cls, scope: str | ScopeId, prefix: str = "id") -> Self:
        return cls(prefix=prefix)

    def new_id(self) -> str:
        self._count += 1
        return f"{self._prefix}-{self._count}"
