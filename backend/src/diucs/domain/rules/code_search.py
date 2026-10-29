"""Search over a list of codes and their display texts (R16).

The text a user types is trimmed and matched without regard to case, as a part of the code or as a
part of the display. Results are in code order and at most `limit`. Text shorter than
MIN_SEARCH_LENGTH after trimming finds nothing, so a search can never return the whole list.
"""

from collections.abc import Sequence
from typing import Final

MIN_SEARCH_LENGTH: Final = 2


def search_codes(
    entries: Sequence[tuple[str, str]], text: str, limit: int
) -> list[tuple[str, str]]:
    # DEC-010 red stub: answers nothing, so every test that expects a match fails on its assertion.
    return []
