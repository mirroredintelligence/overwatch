"""Round 3 (verifier finding): free text on a Practitioner is screened for patient-data shapes.

The display name is a staff name (DEC-065 item 6), so a plain name is allowed. A postcode shape and
an NHS-number shape are refused in it, with the same patterns as DEC-047 items 1 and 2. A refusal
names the field only and never echoes the value.
"""

import pytest

from diucs.domain.errors import ValidationFailed
from diucs.domain.model.people import Practitioner


def _with_name(display_name: str) -> Practitioner:
    return Practitioner(id="p1", active=True, display_name=display_name, phone_hash=None)


@pytest.mark.parametrize("display_name", ["Dr A Example", "Sharon Smith", "Duty Manager One"])
def test_a_plain_staff_name_is_accepted(display_name: str) -> None:
    assert _with_name(display_name).display_name == display_name


@pytest.mark.parametrize(
    "display_name",
    [
        pytest.param("Duty DT4 8XX", id="postcode-shape"),
        pytest.param("Duty DT48XX", id="postcode-shape-no-space"),
    ],
)
def test_a_postcode_shape_in_the_display_name_is_refused(display_name: str) -> None:
    with pytest.raises(ValidationFailed) as refused:
        _with_name(display_name)

    assert refused.value.field == "display_name"
    assert "DT4" not in str(refused.value)


@pytest.mark.parametrize(
    "display_name",
    [
        pytest.param("Duty 943 476 5919", id="nhs-number-shape-spaced"),
        pytest.param("Duty 9434765919", id="nhs-number-shape-contiguous"),
    ],
)
def test_an_nhs_number_shape_in_the_display_name_is_refused(display_name: str) -> None:
    with pytest.raises(ValidationFailed) as refused:
        _with_name(display_name)

    assert refused.value.field == "display_name"
    assert "943" not in str(refused.value)
