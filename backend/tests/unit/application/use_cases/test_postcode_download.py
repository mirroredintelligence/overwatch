"""Step two of the postcode district choice (DEC-1329): the background download stores the points
of a confirmed district, once per postcode, and refuses a prefix that is not a district."""

from collections.abc import Sequence

import pytest

from overwatch.application.ports.outbound.postcode_directory import DirectoryPostcode
from overwatch.application.use_cases.postcode_download import DownloadPostcodePoints


class FakeDirectory:
    def __init__(self, postcodes: list[DirectoryPostcode]) -> None:
        self._postcodes = postcodes
        self.asked: list[str] = []

    async def count(self, prefix: str) -> int:
        raise AssertionError("the download does not count")

    async def postcodes(self, prefix: str) -> list[DirectoryPostcode]:
        self.asked.append(prefix)
        return [
            p
            for p in self._postcodes
            if p.postcode.startswith(prefix.replace(" ", "")) or p.postcode.startswith(prefix)
        ]


class FakeStore:
    def __init__(self) -> None:
        self.by_postcode: dict[str, DirectoryPostcode] = {}

    async def upsert(self, points: Sequence[DirectoryPostcode]) -> int:
        for point in points:
            self.by_postcode[point.postcode] = point
        return len(points)


POINTS = [
    DirectoryPostcode("DT4 0AW", 50.611, -2.462),
    DirectoryPostcode("DT4 0AX", 50.609, -2.462),
    DirectoryPostcode("DT4 8SE", 50.602, -2.456),
]


async def test_the_confirmed_district_points_are_stored_and_counted() -> None:
    store = FakeStore()
    directory = FakeDirectory(POINTS)
    written = await DownloadPostcodePoints(directory, store)("dt4")
    assert written == 3
    assert directory.asked == ["DT4"]
    assert set(store.by_postcode) == {"DT4 0AW", "DT4 0AX", "DT4 8SE"}


async def test_a_retried_download_does_not_add_a_second_point() -> None:
    store = FakeStore()
    download = DownloadPostcodePoints(FakeDirectory(POINTS), store)
    await download("DT4")
    await download("DT4")
    assert len(store.by_postcode) == 3


async def test_a_narrowed_prefix_downloads_only_its_postcodes() -> None:
    store = FakeStore()
    await DownloadPostcodePoints(FakeDirectory(POINTS), store)("DT4 0")
    assert set(store.by_postcode) == {"DT4 0AW", "DT4 0AX"}


@pytest.mark.parametrize("prefix", ["DT4 8SEX", "DT4'; --", "", "not a district"])
async def test_a_prefix_that_is_not_a_district_is_refused_before_any_read(prefix: str) -> None:
    directory = FakeDirectory(POINTS)
    with pytest.raises(ValueError):
        await DownloadPostcodePoints(directory, FakeStore())(prefix)
    assert directory.asked == []
