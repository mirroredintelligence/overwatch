"""The pure parts of reporter set-up (W7C): the stand-in hash and the hasher that holds a hash.

A code request for an invitation or a device that is not usable runs on a stand-in hash that no
practitioner holds, so it does the same work as a request for a real one (H-451). Synthetic ids."""

import re

from diucs.application.use_cases.reporter_setup import (
    STAND_IN_DEVICE,
    STAND_IN_TOKEN,
    KnownPhoneHash,
    stand_in_hash,
)

HASH = re.compile(r"[0-9a-f]{64}")


def test_a_stand_in_hash_has_the_shape_of_a_phone_hash() -> None:
    assert HASH.fullmatch(stand_in_hash(STAND_IN_TOKEN, "AbCdEfGhIjKlMnOpQrStUvW"))


def test_a_stand_in_hash_is_stable_for_one_subject_and_differs_between_subjects_and_kinds() -> None:
    first = stand_in_hash(STAND_IN_TOKEN, "one")

    assert first == stand_in_hash(STAND_IN_TOKEN, "one")
    assert first != stand_in_hash(STAND_IN_TOKEN, "two")
    assert first != stand_in_hash(STAND_IN_DEVICE, "one")


def test_a_stand_in_hash_does_not_hold_its_subject() -> None:
    assert "AbCdEfGh" not in stand_in_hash(STAND_IN_TOKEN, "AbCdEfGhIjKlMnOpQrStUvW")


def test_the_known_hash_hasher_answers_the_hash_it_holds_whatever_it_is_asked_to_hash() -> None:
    held = "a" * 64

    hasher = KnownPhoneHash(held)

    assert hasher.hash("") == held
    assert hasher.hash("07700 900123") == held
