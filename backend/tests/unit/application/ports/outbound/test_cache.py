"""Pure tests of the cache port's values (P09): the channel name and the lock value."""

from dataclasses import FrozenInstanceError

import pytest

from diucs.application.ports.outbound.cache import BOARD_UPDATES_CHANNEL, Lock


def test_the_live_update_channel_is_board_updates() -> None:
    assert BOARD_UPDATES_CHANNEL == "board.updates"


def test_a_lock_is_a_value_with_its_name_and_token() -> None:
    assert Lock("relay", 1) == Lock("relay", 1)
    assert Lock("relay", 1) != Lock("relay", 2)


def test_a_lock_cannot_be_changed_after_it_is_issued() -> None:
    lock = Lock("relay", 1)
    with pytest.raises(FrozenInstanceError):
        lock.fencing_token = 2  # type: ignore[misc]
