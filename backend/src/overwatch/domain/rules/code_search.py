"""Search over a list of codes and their display texts (R16).

The text a user types is trimmed and matched without regard to case, as a part of the code or as a
part of the display (a substring, not only a prefix: the sample "samp" finds every sample code).
Results are in code order and at most `limit`. Text shorter than MIN_SEARCH_LENGTH after trimming
finds nothing, so a search can never return the whole list.
"""

from collections.abc import Sequence
from typing import Final

MIN_SEARCH_LENGTH: Final = 2


def search_codes(
    entries: Sequence[tuple[str, str]], text: str, limit: int
) -> list[tuple[str, str]]:
    needle = text.strip().casefold()
    if len(needle) < MIN_SEARCH_LENGTH:
        return []
    matches = [
        (code, display)
        for code, display in sorted(entries, key=lambda entry: entry[0])
        if needle in code.casefold() or needle in display.casefold()
    ]
    return matches[:limit]
