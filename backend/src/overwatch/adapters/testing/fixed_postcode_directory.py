"""A fixed-table fake for the ONS Postcode Directory port (DEC-1329). It answers from a table the
test writes down and calls no network. A prefix that matches nothing counts zero, the documented
"not found" answer, never a guess.

Prefixes match as the adapter matches them: a bare district takes a space, so DT4 does not match
DT40.
"""

from collections.abc import Mapping, Sequence

from overwatch.application.ports.outbound.postcode_directory import DirectoryPostcode


def _matches(postcode: str, prefix: str) -> bool:
    return postcode.startswith(prefix if " " in prefix else f"{prefix} ")


class FixedPostcodeDirectory:
    def __init__(self, table: Mapping[str, Sequence[DirectoryPostcode]]) -> None:
        self._postcodes = [point for points in table.values() for point in points]

    async def count(self, prefix: str) -> int:
        return sum(1 for point in self._postcodes if _matches(point.postcode, prefix))

    async def postcodes(self, prefix: str) -> list[DirectoryPostcode]:
        return sorted(
            (point for point in self._postcodes if _matches(point.postcode, prefix)),
            key=lambda point: point.postcode,
        )
