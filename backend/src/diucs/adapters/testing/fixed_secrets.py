"""Fake secret store: a fixed mapping of secret names to bytes (P10), recording (TEN-007).

An external-provider fake: the secrets never come from a real vault in tests. It records the name
of every secret asked for, in order, hits and misses, so a test can show that the right tenant's
reference was read and no other. It records names only and never shows a value: not in its
repr, not in `vars()`, not in a refusal, and not in what it records. Values given here are
obviously fake (`b"test-only-..."`); no real credential belongs in a test.
"""

from collections.abc import Mapping

from diucs.domain.errors import NotFound


class _Values:
    """The secret values, behind a repr that shows none, so that printing the store or its
    `vars()` in a failure message or a log cannot show one."""

    def __init__(self, values: dict[str, bytes]) -> None:
        self._values = values

    def get(self, name: str) -> bytes:
        return self._values[name]

    def names(self) -> frozenset[str]:
        return frozenset(self._values)

    def __repr__(self) -> str:
        return f"<{len(self._values)} secrets hidden>"


class FixedSecretStore:
    def __init__(self, secrets: Mapping[str, bytes]) -> None:
        for name, value in secrets.items():
            if type(name) is not str or not name:
                raise TypeError("a secret name must be a non-empty text")
            if type(value) is not bytes:
                raise TypeError("a secret value must be bytes")
        self._secrets = _Values(dict(secrets))
        self._requested: list[str] = []

    def get(self, name: str) -> bytes:
        self._requested.append(name)
        try:
            return self._secrets.get(name)
        except KeyError:
            raise NotFound(f"secret {name}") from None

    @property
    def requested(self) -> tuple[str, ...]:
        """The name of every secret asked for, in order, including those that were not there."""
        return tuple(self._requested)

    def read_count(self, name: str) -> int:
        return self._requested.count(name)

    @property
    def names(self) -> frozenset[str]:
        """The names the store holds, never the values."""
        return self._secrets.names()

    def __repr__(self) -> str:
        return f"FixedSecretStore(names={sorted(self._secrets.names())})"
