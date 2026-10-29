"""Unit tests for the wall screen device record (U10, DEC-160). Values are synthetic."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from diucs.domain.errors import ValidationFailed
from diucs.domain.model.device import (
    SCREEN_LABEL_MAX,
    BoardScope,
    Device,
    DeviceStatus,
    DeviceType,
    check_screen_label,
)

HASH = "a" * 64


def _device(**changes: object) -> Device:
    values: dict[str, object] = {
        "id": "screen-1",
        "status": DeviceStatus.ACTIVE,
        "name": "Ward 4 corridor",
        "location": "Level 2",
        "device_type": DeviceType.WALL_DISPLAY,
        "token_hash": HASH,
    }
    values.update(changes)
    return Device(**values)  # type: ignore[arg-type]


def test_a_label_is_trimmed_and_kept() -> None:
    assert check_screen_label("  Ward 4 corridor ", "screen_name") == "Ward 4 corridor"


@pytest.mark.parametrize("text", ["", "   ", "\t\n"])
def test_an_empty_label_is_refused_by_field_name(text: str) -> None:
    with pytest.raises(ValidationFailed) as refused:
        check_screen_label(text, "screen_name")
    assert refused.value.field == "screen_name"


def test_a_label_of_exactly_the_limit_is_kept_and_one_more_is_refused() -> None:
    assert check_screen_label("x" * SCREEN_LABEL_MAX, "location") == "x" * SCREEN_LABEL_MAX
    with pytest.raises(ValidationFailed) as refused:
        check_screen_label("x" * (SCREEN_LABEL_MAX + 1), "location")
    assert refused.value.field == "location"


@pytest.mark.parametrize("text", ["Ward\x004", "Ward\n4", "Ward 4", "Ward\x7f4"])
def test_a_control_character_is_refused(text: str) -> None:
    with pytest.raises(ValidationFailed):
        check_screen_label(text, "screen_name")


def test_a_non_string_label_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        check_screen_label(42, "screen_name")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "text", ["DT4 8XX corridor", "Bay 943 476 5919", "Mrs Smith bay", "Room dt48xx"]
)
def test_a_label_with_a_patient_data_shape_is_refused_without_echoing_it(text: str) -> None:
    with pytest.raises(ValidationFailed) as refused:
        check_screen_label(text, "screen_name")
    assert text not in str(refused.value)
    assert "8XX" not in str(refused.value)


def test_an_outward_code_alone_is_a_place_not_a_postcode() -> None:
    assert check_screen_label("DT4 outpatients", "location") == "DT4 outpatients"


@given(st.text(max_size=200))
def test_a_label_is_either_refused_or_a_short_trimmed_text(text: str) -> None:
    try:
        label = check_screen_label(text, "screen_name")
    except ValidationFailed as refused:
        assert refused.field == "screen_name"
        return
    assert label == label.strip()
    assert 1 <= len(label) <= SCREEN_LABEL_MAX
    assert label.isprintable()


def test_the_device_trims_its_name_and_defaults_to_the_tenant_board() -> None:
    device = _device(name="  Ward 4 corridor ")
    assert device.name == "Ward 4 corridor"
    assert device.board_scope is BoardScope.TENANT


def test_a_location_is_optional_and_checked_when_given() -> None:
    assert _device(location=None).location is None
    with pytest.raises(ValidationFailed) as refused:
        _device(location="DT4 8XX")
    assert refused.value.field == "location"


def test_an_unclaimed_screen_has_no_token_hash() -> None:
    assert _device(status=DeviceStatus.PAIRED_UNCLAIMED, token_hash=None).token_hash is None
    with pytest.raises(ValidationFailed) as refused:
        _device(status=DeviceStatus.PAIRED_UNCLAIMED, token_hash=HASH)
    assert refused.value.field == "token_hash"


def test_an_active_screen_needs_a_token_hash() -> None:
    with pytest.raises(ValidationFailed) as refused:
        _device(status=DeviceStatus.ACTIVE, token_hash=None)
    assert refused.value.field == "token_hash"


def test_a_revoked_screen_may_keep_or_lose_its_hash() -> None:
    assert _device(status=DeviceStatus.REVOKED, token_hash=HASH).status is DeviceStatus.REVOKED
    assert _device(status=DeviceStatus.REVOKED, token_hash=None).token_hash is None


@pytest.mark.parametrize("text", ["abc", "A" * 64, "g" * 64, "a" * 63, "a" * 65, ""])
def test_a_token_hash_must_be_64_lower_case_hex_characters(text: str) -> None:
    with pytest.raises(ValidationFailed) as refused:
        _device(token_hash=text)
    assert refused.value.field == "token_hash"
    assert text not in str(refused.value) or text == ""


def test_the_status_type_and_scope_values_are_the_stored_words() -> None:
    assert [s.value for s in DeviceStatus] == ["paired-unclaimed", "active", "revoked"]
    assert [t.value for t in DeviceType] == ["wall-display"]
    assert [b.value for b in BoardScope] == ["tenant", "network"]
