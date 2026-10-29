"""The order of delivery statuses (I08): a status only moves forward, and delivered and failed are
final. `statuses_before(new)` is the list of statuses a record may move from."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from diucs.application.ports.outbound.messaging import (
    DELIVERY_STATUSES,
    GROUPED_STATUS,
    statuses_before,
)

FINAL = ("delivered", "failed")


@pytest.mark.parametrize(
    ("new", "before"),
    [
        ("queued", ()),
        ("sent", ("queued",)),
        ("delivered", ("queued", "sent")),
        ("failed", ("queued", "sent")),
    ],
)
def test_a_status_may_be_reached_from_the_ones_before_it_only(
    new: str, before: tuple[str, ...]
) -> None:
    assert tuple(sorted(statuses_before(new))) == tuple(sorted(before))


@pytest.mark.parametrize("new", ["received", GROUPED_STATUS])
def test_a_status_a_receipt_never_sets_is_reached_from_nothing(new: str) -> None:
    assert statuses_before(new) == ()


def test_an_unknown_status_is_refused() -> None:
    with pytest.raises(ValueError, match="status"):
        statuses_before("lost")


@given(new=st.sampled_from(sorted(DELIVERY_STATUSES)))
def test_a_final_status_is_never_left_and_a_status_never_follows_itself(new: str) -> None:
    before = statuses_before(new)

    assert new not in before
    assert not set(before) & set(FINAL)
    assert set(before) <= DELIVERY_STATUSES
