"""Outbound port: the hourly samples of a network board, in the network scope (TEN-082).

A sample is a count of what the board showed in one hour (`domain/rules/network_sample.py`): no
organisation, service, grant or source tenant. Written by the board projector's rebuild (a unit of
work bound to the network scope that is not read-only) and read by the network week summary (a
read-only unit). Kept apart from `NetworkView` and `ProjectionWriter` so that the member-facing
reads of a projection can be shown to hold none of it.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from diucs.domain.rules.network_sample import NetworkSample


class NetworkSamples(Protocol):
    async def record(self, sample: NetworkSample) -> bool:
        """File the sample under its hour. A first sample of the hour creates it; a later one
        replaces its counts and keeps the highest pressure the hour saw; an older one than the hour
        already holds changes the pressure peak only. True when the counts were written."""
        ...

    async def between(self, start: datetime, end: datetime) -> Sequence[NetworkSample]:
        """The samples whose hour is in [start, end), oldest first. Each carries the highest
        pressure of its hour."""
        ...
