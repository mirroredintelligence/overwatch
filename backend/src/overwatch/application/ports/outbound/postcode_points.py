"""Outbound port for the shared postcode points (DEC-1329): the postcodes of the confirmed
districts, held once for every tenant. The graph adapter is not built yet (see the decision). The
download job runs against this port and is tested with an in-memory fake.

Writes are idempotent by postcode, so a retried download never adds a second point.
"""

from collections.abc import Sequence
from typing import Protocol

from overwatch.application.ports.outbound.postcode_directory import DirectoryPostcode


class PostcodePointStore(Protocol):
    async def upsert(self, points: Sequence[DirectoryPostcode]) -> int:
        """Store or refresh the points, keyed by postcode. Returns the number written."""
        ...
