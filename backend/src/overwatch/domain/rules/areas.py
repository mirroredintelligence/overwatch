"""Named areas over postcode districts (DEC-1375).

The services are placed by postcode district (the districts they cover). An organisation reads them
better in a few named areas, so a table groups districts into areas: each area has a name, a short
line of the places in it, and the districts it holds. The table is data, read from a file that names
nothing the code knows; a deployment with no table has no areas and the pages show districts as
before.

Placement. A service is in exactly one group, so the counts add up to the total:
- the districts it covers, or, when it covers none, the district of its own site;
- all of them in one area: that area;
- in more than one area: the network-wide group (`network`), when the table has one;
- none known, or only districts the table leaves out: not placed (None).
"""

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from overwatch.domain.rules.postcode import normalise_district

NETWORK: Final = "network"
_ID: Final = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
_TEXT_MAX: Final = 120


@dataclass(frozen=True, slots=True)
class Area:
    id: str
    name: str
    places: str


@dataclass(frozen=True, slots=True)
class AreaTable:
    name: str
    areas: tuple[Area, ...]
    """The named areas in display order."""
    network: Area | None
    """The group for a service that works across areas; None when the table has none."""
    district_area: Mapping[str, str]
    """Postcode district to the id of its area. A district not here is outside every area."""

    def ordered(self) -> tuple[Area, ...]:
        """The areas for display: the named ones, then the network-wide one."""
        return (*self.areas, *(() if self.network is None else (self.network,)))

    def area_of(self, district: str) -> str | None:
        key = normalise_district(district)
        return None if key is None else self.district_area.get(key)

    def place(self, covered: Iterable[str], site_district: str | None = None) -> str | None:
        """The one group a service is in (see the module text)."""
        districts = list(covered) or ([] if site_district is None else [site_district])
        found = {area for area in (self.area_of(d) for d in districts) if area is not None}
        if len(found) == 1:
            return next(iter(found))
        if len(found) > 1:
            return None if self.network is None else self.network.id
        return None


def _text(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > _TEXT_MAX:
        raise ValueError(f"{what} must be short text")
    return value.strip()


def _area(raw: Any) -> Area:
    if not isinstance(raw, dict):
        raise ValueError("an area must be an object")
    area_id = raw.get("id")
    if not isinstance(area_id, str) or _ID.fullmatch(area_id) is None:
        raise ValueError("an area id must be lower case letters, digits and hyphens")
    return Area(area_id, _text(raw.get("name"), "an area name"), _text(raw.get("places"), "places"))


def parse_area_table(data: Any) -> AreaTable:
    """The table from its parsed JSON; a ValueError, with no value in it, when it is not usable."""
    if not isinstance(data, dict):
        raise ValueError("the area table must be an object")
    areas = tuple(_area(item) for item in data.get("areas", []))
    network = None if data.get("network") is None else _area(data["network"])
    ids = [area.id for area in areas]
    if len(set(ids)) != len(ids) or (network is not None and network.id in ids):
        raise ValueError("area ids must be different")
    if network is not None and network.id != NETWORK:
        raise ValueError("the network-wide group has the id 'network'")
    held = set(ids)
    districts: dict[str, str] = {}
    raw = data.get("districts")
    if not isinstance(raw, dict) or not raw:
        raise ValueError("the table needs its districts")
    for district, area_id in raw.items():
        key = normalise_district(district) if isinstance(district, str) else None
        if key is None or key != district:
            raise ValueError("a district must be a postcode district such as DT4")
        if area_id not in held:
            raise ValueError("a district names an area the table does not have")
        districts[key] = area_id
    return AreaTable(_text(data.get("name"), "the table's name"), areas, network, districts)


def load_area_table(path: Path | str) -> AreaTable:
    """The table in this JSON file. The file is read once, at start-up, so a bad one stops it."""
    with open(path, encoding="utf-8") as handle:
        return parse_area_table(json.load(handle))
