"""Test identifier generator that counts up: prefix-1, prefix-2, ..."""

from typing import Self

from diucs.application.tenancy import ScopeId


class SequentialIds:
    def __init__(self, prefix: str = "id") -> None:
        self._prefix = prefix
        self._count = 0

    @classmethod
    def scoped(cls, scope: str | ScopeId, prefix: str = "id") -> Self:
        """A generator whose ids start with the scope: `a1-id-1`, `a1-id-2`, or
        `a1-booking-1` for prefix `booking` (TEN-003). For tests that need ids that cannot clash in
        a global namespace (the Service Bus emulator, Redis keys); the isolation tests deliberately
        use the default generator in both tenants so the same id appears in both. A scope that is
        not a valid tenant or network id is refused (ScopeInvalid)."""
        parsed = scope if isinstance(scope, ScopeId) else ScopeId.parse(scope)
        return cls(prefix=f"{parsed}-{prefix}")

    def new_id(self) -> str:
        self._count += 1
        return f"{self._prefix}-{self._count}"
