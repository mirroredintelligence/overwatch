"""Step one of choosing a service's postcode districts (DEC-1329): check that the district the
admin typed exists and count its postcodes, so they can confirm or narrow it before any download.

The check is one count request, never a list. A district with no postcodes, or one that is not a
district, is answered with None: the form then says the district was not found.
"""

from dataclasses import dataclass

from overwatch.application.ports.outbound.postcode_directory import PostcodeDirectory
from overwatch.domain.rules.postcode import partial_district


@dataclass(frozen=True, slots=True)
class DistrictCheck:
    prefix: str  # "DT4", or a narrower "DT4 0" when the admin typed an inward start
    postcodes: int


class CheckPostcodeDistrict:
    def __init__(self, directory: PostcodeDirectory) -> None:
        self._directory = directory

    async def __call__(self, text: str) -> DistrictCheck | None:
        district = partial_district(text)
        if district is None:
            return None
        prefix = " ".join(text.split()).upper()
        if prefix.split()[0] != district:
            return None
        count = await self._directory.count(prefix)
        if count == 0:
            return None
        return DistrictCheck(prefix=prefix, postcodes=count)
