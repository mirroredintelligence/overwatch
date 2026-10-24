from diucs.adapters.testing.fixed_ids import SequentialIds


def test_default_prefix_counts_up_from_one() -> None:
    ids = SequentialIds()
    assert ids.new_id() == "id-1"
    assert ids.new_id() == "id-2"


def test_custom_prefix_is_used() -> None:
    ids = SequentialIds(prefix="booking")
    assert ids.new_id() == "booking-1"


def test_each_instance_counts_separately() -> None:
    first = SequentialIds()
    second = SequentialIds()
    first.new_id()
    assert second.new_id() == "id-1"
