"""Place services in named areas for the overview pages (DEC-1375).

A service is placed from the districts it covers; one that covers none is placed from the district
of its own site, found as the nearest postcode in the local file. Nothing here is stored.
"""

from collections.abc import Mapping, Sequence

from overwatch.application.ports.outbound.geo import PostcodeLocator
from overwatch.application.ports.outbound.unit_of_work import UnitOfWork
from overwatch.domain.rules.areas import AreaTable


async def site_districts(
    uow: UnitOfWork,
    service_ids: Sequence[str],
    covered: Mapping[str, tuple[str, ...]],
    table: AreaTable | None,
    locator: PostcodeLocator | None,
) -> dict[str, str]:
    """The district of the site of each service that covers no district. Empty when there is no
    table or no locator, or no service needs one."""
    if table is None or locator is None:
        return {}
    missing = [service_id for service_id in service_ids if not covered.get(service_id)]
    if not missing:
        return {}
    found: dict[str, str] = {}
    for service_id, position in (await uow.positions.get_many(missing)).items():
        district = locator.district_at(position.lat, position.lon)
        if district is not None:
            found[service_id] = district
    return found


def place_services(
    table: AreaTable | None,
    service_ids: Sequence[str],
    covered: Mapping[str, tuple[str, ...]],
    sites: Mapping[str, str],
) -> dict[str, str | None]:
    """The group of each service, or None for not placed. Empty when there is no table."""
    if table is None:
        return {}
    return {
        service_id: table.place(covered.get(service_id, ()), sites.get(service_id))
        for service_id in service_ids
    }
