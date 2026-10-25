"""Fake secret store: a fixed mapping of secret names to bytes (P10). External-provider fake only.

Stub for the red commit (DEC-010).
"""


class FixedSecretStore:
    def __init__(self, secrets: dict[str, bytes]) -> None:
        self._secrets = dict(secrets)

    def get(self, name: str) -> bytes:
        raise NotImplementedError
