"""Phone hashing for identity lookups (P10, H-09). Phone numbers are stored only as keyed hashes.

Stub for the red commit (DEC-010): the functions raise NotImplementedError until the green commit.
"""

from typing import Protocol

from diucs.application.ports.outbound.tokens import SecretStore


class PhoneHasher(Protocol):
    def hash(self, number: str) -> str: ...


class HmacPhoneHasher:
    def __init__(self, secrets: SecretStore) -> None:
        self._secrets = secrets

    def hash(self, number: str) -> str:
        raise NotImplementedError


def normalise_uk_mobile(number: str) -> str:
    raise NotImplementedError
