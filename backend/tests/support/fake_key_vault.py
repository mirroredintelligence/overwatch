"""A fake of the Key Vault `SecretClient` (B8, DEC-1304): the shape the adapter calls, no network.

It records the name of every secret asked for (the vault name, as the adapter sends it), answers
from a mapping of text values, and can be told to fail the way the service fails: not found (the
real client's `ResourceNotFoundError`) or any other error. Values are obviously fake text; no real
credential belongs in a test. It never shows a value in its repr.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from threading import Event

from azure.core.exceptions import HttpResponseError, ResourceNotFoundError


@dataclass(frozen=True, slots=True)
class FakeSecretBundle:
    """What `get_secret` returns: the value (None for a secret with no value)."""

    value: str | None

    def __repr__(self) -> str:
        return "FakeSecretBundle(value=<hidden>)"


class FakeKeyVaultClient:
    def __init__(self, secrets: Mapping[str, str | None] | None = None) -> None:
        self.secrets: dict[str, str | None] = dict(secrets or {})
        self.calls: list[str] = []
        self.closed = False
        self.failure: Exception | None = None
        self.gate: Event | None = None
        self.entered = Event()
        self.on_call: Callable[[str], None] | None = None

    def get_secret(self, name: str, version: str | None = None, **kwargs: object) -> FakeSecretBundle:
        self.calls.append(name)
        self.entered.set()
        if self.gate is not None:
            self.gate.wait(timeout=5)
        if self.on_call is not None:
            self.on_call(name)
        if self.failure is not None:
            raise self.failure
        if name not in self.secrets:
            raise ResourceNotFoundError(f"(SecretNotFound) A secret with name {name} was not found")
        return FakeSecretBundle(self.secrets[name])

    def close(self) -> None:
        self.closed = True

    def fail(self, error: Exception | None = None) -> None:
        """Every read fails with `error` (a 503 by default) until `recover`."""
        self.failure = error or HttpResponseError("the vault is unavailable")

    def recover(self) -> None:
        self.failure = None

    def calls_for(self, name: str) -> int:
        return self.calls.count(name)

    def __repr__(self) -> str:
        return f"FakeKeyVaultClient(<{len(self.secrets)} secrets hidden>)"


class FakeMonotonic:
    """The clock of the cache: seconds, moved by the test."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds
