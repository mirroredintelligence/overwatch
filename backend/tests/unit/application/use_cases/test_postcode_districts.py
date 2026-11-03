"""Step one of the postcode district choice (DEC-1329): verify and count, no list."""

from overwatch.application.ports.outbound.postcode_directory import DirectoryPostcode
from overwatch.application.use_cases.postcode_districts import CheckPostcodeDistrict


class CountingDirectory:
    def __init__(self, counts: dict[str, int]) -> None:
        self._counts = counts
        self.counted: list[str] = []

    async def count(self, prefix: str) -> int:
        self.counted.append(prefix)
        return self._counts.get(prefix, 0)

    async def postcodes(self, prefix: str) -> list[DirectoryPostcode]:
        raise AssertionError("the check must not list postcodes")


async def test_a_known_district_is_confirmed_with_its_count_and_one_count_request() -> None:
    directory = CountingDirectory({"DT4": 1505})
    check = await CheckPostcodeDistrict(directory)("dt4")
    assert check is not None
    assert (check.prefix, check.postcodes) == ("DT4", 1505)
    assert directory.counted == ["DT4"]


async def test_a_typed_inward_start_narrows_the_prefix() -> None:
    directory = CountingDirectory({"DT4 0": 310})
    check = await CheckPostcodeDistrict(directory)("dt4  0")
    assert check is not None
    assert (check.prefix, check.postcodes) == ("DT4 0", 310)


async def test_a_district_with_no_postcodes_is_not_found() -> None:
    assert await CheckPostcodeDistrict(CountingDirectory({}))("ZZ99") is None


async def test_text_that_is_not_a_district_is_refused_without_a_request() -> None:
    directory = CountingDirectory({"DT4": 1505})
    assert await CheckPostcodeDistrict(directory)("DT4 ABC") is None
    assert await CheckPostcodeDistrict(directory)("DT4'; --") is None
    assert directory.counted == []
