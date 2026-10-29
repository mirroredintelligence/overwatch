"""The fixed secret store returns the bytes it was given and refuses an unknown secret (P10), and,
as the recording fake of TEN-007, notes every name asked for and never a value."""

import pytest

from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.domain.errors import NotFound

TOKEN = b"test-only-auth-token-0001"


def test_a_known_secret_is_returned_as_bytes() -> None:
    store = FixedSecretStore({"link-token": b"secret-one"})
    assert store.get("link-token") == b"secret-one"


def test_an_unknown_secret_is_not_found_and_names_the_secret() -> None:
    store = FixedSecretStore({"link-token": b"secret-one"})
    with pytest.raises(NotFound, match="phone-hash"):
        store.get("phone-hash")


def test_the_store_records_every_name_asked_for_in_order_hits_and_misses() -> None:
    store = FixedSecretStore({"link-token": b"one", "phone-hash": b"two"})
    assert store.requested == ()
    store.get("phone-hash")
    with pytest.raises(NotFound):
        store.get("nothing")
    store.get("link-token")
    store.get("phone-hash")
    assert store.requested == ("phone-hash", "nothing", "link-token", "phone-hash")
    assert store.read_count("phone-hash") == 2
    assert store.read_count("nothing") == 1
    assert store.read_count("never-asked") == 0


def test_the_record_holds_names_never_values() -> None:
    store = FixedSecretStore({"twilio/example-icb/auth-token": TOKEN})
    store.get("twilio/example-icb/auth-token")
    assert all(isinstance(name, str) for name in store.requested)
    assert TOKEN.decode() not in repr(store.requested)


def test_the_store_does_not_show_a_value_when_printed() -> None:
    store = FixedSecretStore({"twilio/example-icb/auth-token": TOKEN})
    store.get("twilio/example-icb/auth-token")
    for text in (repr(store), str(store), f"{store!r}", repr(vars(store))):
        assert TOKEN.decode() not in text
        assert "auth-token-0001" not in text


def test_the_names_the_store_holds_are_listed_without_values() -> None:
    store = FixedSecretStore({"a-secret": b"x", "b-secret": b"y"})
    assert store.names == frozenset({"a-secret", "b-secret"})


def test_a_change_to_the_dict_that_was_passed_in_changes_nothing() -> None:
    given = {"link-token": b"one"}
    store = FixedSecretStore(given)
    given["link-token"] = b"changed"
    given["extra"] = b"new"
    assert store.get("link-token") == b"one"
    with pytest.raises(NotFound):
        store.get("extra")


@pytest.mark.parametrize("value", ["a text", 5, None, bytearray(b"x")])
def test_a_value_that_is_not_bytes_is_refused_without_repeating_it(value: object) -> None:
    with pytest.raises(TypeError) as raised:
        FixedSecretStore({"link-token": value})  # type: ignore[dict-item]
    assert str(value) not in str(raised.value) or str(value) == "None"


@pytest.mark.parametrize("name", ["", 5, None])
def test_a_name_that_is_not_a_text_is_refused(name: object) -> None:
    with pytest.raises(TypeError):
        FixedSecretStore({name: b"x"})  # type: ignore[dict-item]
