"""The state of a wall screen as the lead's list shows it, and the revoke transition (W9I, TEN-072).

A screen is online when it was seen within the window (it reads the board every minute), offline
when it was not, waiting while the pairing window is open and it has not yet collected its token,
never connected when that window ran out first, and revoked once a lead ended it. Values are
synthetic.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from diucs.domain.model.device import (
    ONLINE_WITHIN,
    Device,
    DeviceStatus,
    DeviceType,
    ScreenState,
    screen_state,
)
from diucs.domain.rules.tokens import PAIRING_CODE_VALID_FOR

NOW = datetime(2026, 10, 30, 10, 0, tzinfo=UTC)
HASH = "a" * 64


def _screen(**changes: object) -> Device:
    values: dict[str, object] = {
        "id": "screen-1",
        "status": DeviceStatus.ACTIVE,
        "name": "Ward 4 corridor",
        "location": None,
        "device_type": DeviceType.WALL_DISPLAY,
        "token_hash": HASH,
        "paired_at": NOW - timedelta(days=2),
        "last_seen_at": NOW - timedelta(seconds=30),
    }
    values.update(changes)
    return Device(**values)  # type: ignore[arg-type]


def test_a_screen_seen_inside_the_window_is_online() -> None:
    assert screen_state(_screen(), NOW) is ScreenState.ONLINE


def test_the_window_edge_is_online_and_one_second_past_it_is_offline() -> None:
    edge = _screen(last_seen_at=NOW - ONLINE_WITHIN)
    past = _screen(last_seen_at=NOW - ONLINE_WITHIN - timedelta(seconds=1))
    assert screen_state(edge, NOW) is ScreenState.ONLINE
    assert screen_state(past, NOW) is ScreenState.OFFLINE


def test_an_active_screen_never_seen_is_offline() -> None:
    assert screen_state(_screen(last_seen_at=None), NOW) is ScreenState.OFFLINE


def test_a_last_seen_time_in_the_future_is_not_taken_as_online_forever() -> None:
    skewed = _screen(last_seen_at=NOW + timedelta(hours=3))
    assert screen_state(skewed, NOW) is ScreenState.OFFLINE


def test_a_screen_that_has_not_collected_its_token_waits_while_the_pairing_window_is_open() -> None:
    waiting = _screen(
        status=DeviceStatus.PAIRED_UNCLAIMED,
        token_hash=None,
        last_seen_at=None,
        paired_at=NOW - timedelta(minutes=2),
    )
    assert screen_state(waiting, NOW) is ScreenState.WAITING


def test_the_pairing_window_ends_exactly_at_its_length() -> None:
    base = {"status": DeviceStatus.PAIRED_UNCLAIMED, "token_hash": None, "last_seen_at": None}
    inside = _screen(**base, paired_at=NOW - PAIRING_CODE_VALID_FOR + timedelta(seconds=1))
    at_end = _screen(**base, paired_at=NOW - PAIRING_CODE_VALID_FOR)
    assert screen_state(inside, NOW) is ScreenState.WAITING
    assert screen_state(at_end, NOW) is ScreenState.NEVER_CONNECTED


def test_an_unclaimed_screen_with_no_pairing_time_is_never_connected() -> None:
    old = _screen(
        status=DeviceStatus.PAIRED_UNCLAIMED, token_hash=None, last_seen_at=None, paired_at=None
    )
    assert screen_state(old, NOW) is ScreenState.NEVER_CONNECTED


def test_a_revoked_screen_is_revoked_whatever_it_was_last_seen_doing() -> None:
    revoked = _screen(status=DeviceStatus.REVOKED, token_hash=None, last_seen_at=NOW)
    assert screen_state(revoked, NOW) is ScreenState.REVOKED


def test_revoking_ends_the_screen_and_drops_its_token_hash() -> None:
    ended = _screen().revoke(NOW)
    assert ended.status is DeviceStatus.REVOKED
    assert ended.token_hash is None
    assert ended.revoked_at == NOW
    assert ended.name == "Ward 4 corridor"
    assert ended.paired_at == NOW - timedelta(days=2)


def test_revoking_a_screen_that_never_collected_its_token_works_too() -> None:
    waiting = _screen(status=DeviceStatus.PAIRED_UNCLAIMED, token_hash=None)
    assert waiting.revoke(NOW).status is DeviceStatus.REVOKED


def test_revoking_a_revoked_screen_keeps_the_first_time() -> None:
    first = _screen().revoke(NOW)
    again = first.revoke(NOW + timedelta(hours=1))
    assert again == first


def test_a_device_still_has_the_fields_it_had_before() -> None:
    plain = replace(_screen(), paired_at=None, last_seen_at=None)
    assert plain.revoked_at is None
