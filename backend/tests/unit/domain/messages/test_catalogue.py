"""Tests for diucs.domain.messages.catalogue: the message ids (D15).

Source: docs/spec/domain-rules.md section 9 (catalogue id table).
"""

from diucs.domain.messages.catalogue import MessageId


def test_catalogue_has_every_id_from_the_rule_book() -> None:
    expected = (
        [f"C{n}" for n in range(1, 13)]
        + [f"B{n}" for n in range(1, 10)]
        + [f"I{n}" for n in range(1, 4)]
        + [f"K{n}" for n in range(1, 5)]
    )
    assert [m.value for m in MessageId] == expected


def test_each_id_is_its_own_value() -> None:
    assert MessageId.C1 == "C1"
    assert MessageId("C11") is MessageId.C11
    assert MessageId("C12") is MessageId.C12
