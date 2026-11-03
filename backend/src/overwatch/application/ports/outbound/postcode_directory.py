"""Outbound port for the ONS Postcode Directory (DEC-1329): the postcodes of a district or of a
narrower prefix, with each postcode's point.

The directory is shared public geography, so it is not tenant-scoped. The port answers two
questions: how many postcodes a prefix has (for the admin to confirm or narrow), and the postcodes
themselves (for the background download). Prefixes are checked by the adapter before any request.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class DirectoryPostcode:
    postcode: str  # the full postcode, with one space, for example "DT4 0AW"
    lat: float
    lon: float


class PostcodeDirectory(Protocol):
    async def count(self, prefix: str) -> int:
        """The number of postcodes whose outward code, or whose outward code and typed inward
        start, is `prefix` ("DT4" or "DT4 0")."""
        ...

    async def postcodes(self, prefix: str) -> list[DirectoryPostcode]:
        """Every postcode the prefix matches, in postcode order."""
        ...
