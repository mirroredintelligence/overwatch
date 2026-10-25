"""The fixed secret store returns the bytes it was given and refuses an unknown secret (P10)."""

import pytest

from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.domain.errors import NotFound


def test_a_known_secret_is_returned_as_bytes() -> None:
    store = FixedSecretStore({"link-token": b"secret-one"})
    assert store.get("link-token") == b"secret-one"


def test_an_unknown_secret_is_not_found_and_names_the_secret() -> None:
    store = FixedSecretStore({"link-token": b"secret-one"})
    with pytest.raises(NotFound, match="phone-hash"):
        store.get("phone-hash")
