"""The area of each tenant for the registration review (U28, DEC-317).

The area is the tenant's own and there is no default: a tenant with no entry in the settings
`tenant_areas` has an empty area, which fails every address check rather than inherit another
tenant's. Settings are parsed once, at start-up, so a typo stops the process instead of quietly
narrowing an area.
"""

import re
from collections.abc import Mapping
from typing import Final

from diucs.application.tenancy import ScopeId, ScopeKind
from diucs.application.use_cases.review_registration import AreaDistrictsFor, districts_in_ranges
from diucs.domain.rules.postcode import normalise_district

_RUN: Final = re.compile(r"([A-Za-z]{1,2})([0-9]{1,2})-([A-Za-z]{1,2})([0-9]{1,2})")


def parse_area(text: str) -> frozenset[str]:
    """The districts of a tenant's area, written as comma-separated districts and runs: "DT1-DT11,
    BH1-BH31, DT4". A run has one prefix. Anything else is a ValueError, so a typo in the settings
    stops the process at start-up instead of quietly narrowing an area."""
    districts: set[str] = set()
    parts = [part.strip() for part in text.split(",")]
    for part in parts:
        run = _RUN.fullmatch(part)
        if run is not None:
            first, low, second, high = run.groups()
            if first.upper() != second.upper():
                raise ValueError("an area run must keep one prefix, like DT1-DT11")
            try:
                districts |= districts_in_ranges((first.upper(), int(low), int(high)))
            except Exception as error:
                raise ValueError("an area run must go from a lower number to a higher") from error
            continue
        district = normalise_district(part)
        if district is None:
            raise ValueError("an area is districts and runs, like DT1-DT11, BH7")
        districts.add(district)
    return frozenset(districts)


def area_districts_for(areas: Mapping[str, str]) -> AreaDistrictsFor:
    """The review's source of a tenant's area: parsed once, here, so a bad setting fails at
    start-up. A tenant with no entry, and a network scope, have an empty area."""
    parsed = {tenant: parse_area(text) for tenant, text in areas.items()}

    def districts_for(scope: ScopeId) -> frozenset[str]:
        if scope.kind is not ScopeKind.TENANT:
            return frozenset()
        return parsed.get(scope.value, frozenset())

    return districts_for
