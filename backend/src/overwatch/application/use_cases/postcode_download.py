"""Step two of choosing a service's postcode districts (DEC-1329): once the admin has confirmed the
district, the background job reads its postcodes from the ONS directory and stores their points.

The prefix is checked again here, because the job runs later and from a queued request, not from the
form. A prefix that is not a district or a typed start of one is refused before any read.
"""

from overwatch.application.ports.outbound.postcode_directory import PostcodeDirectory
from overwatch.application.ports.outbound.postcode_points import PostcodePointStore
from overwatch.domain.rules.postcode import partial_district


class DownloadPostcodePoints:
    def __init__(self, directory: PostcodeDirectory, store: PostcodePointStore) -> None:
        self._directory = directory
        self._store = store

    async def __call__(self, prefix: str) -> int:
        normalised = " ".join(prefix.split()).upper()
        if partial_district(normalised) is None:
            raise ValueError("the prefix is not a postcode district")
        points = await self._directory.postcodes(normalised)
        return await self._store.upsert(points)
