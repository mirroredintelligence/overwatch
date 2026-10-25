"""Reference bounds for new_reference (D14), pinned without a random draw.

Rules: docs/spec/domain-rules.md section 3.2 bullet 8 [ASSUMED]; DEC-007 (4-digit references).
Split from test_booking_rules.py so that the red test file stays byte-identical to its red commit.
"""

import random

from diucs.domain.rules.booking_rules import new_reference

# Reference bounds, pinned with a recording rng so no draw is needed to see the range.
# The generator must ask randint for exactly 1000 to 9999 inclusive (DEC-007, 4 digits, no zero).


class _RecordingRng(random.Random):
    def __init__(self, draw: int) -> None:
        super().__init__(0)
        self.draw = draw
        self.bounds: list[tuple[int, int]] = []

    def randint(self, a: int, b: int) -> int:
        self.bounds.append((a, b))
        return self.draw


def test_references_are_drawn_from_exactly_1000_to_9999_inclusive() -> None:
    rng = _RecordingRng(draw=1000)
    new_reference(rng, set())
    assert rng.bounds == [(1000, 9999)]


def test_the_lowest_draw_1000_is_a_reference() -> None:
    assert new_reference(_RecordingRng(draw=1000), set()) == "1000"


def test_the_highest_draw_9999_is_a_reference() -> None:
    assert new_reference(_RecordingRng(draw=9999), set()) == "9999"
