"""Fake secret store: a fixed mapping of secret names to bytes (P10).

An external-provider fake: the secrets never come from a real vault in tests.
"""

from diucs.domain.errors import NotFound


class FixedSecretStore:
    def __init__(self, secrets: dict[str, bytes]) -> None:
        self._secrets = dict(secrets)

    def get(self, name: str) -> bytes:
        try:
            return self._secrets[name]
        except KeyError:
            raise NotFound(f"secret {name}") from None
