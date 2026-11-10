"""ReadServiceDetail: what the one service detail page shows (DEC-1367).

The page is the same for the Analytics User and for the advisor pages (Advisor, Advisor v2): the
service's name and group, how its capacity stands, when it reports, the number to phone it, when it
is open, what it potentially accepts and excludes, and the districts it covers. It is the narrowest
read that holds those: the board's entry for the service (the same figures the advisor's cards
read), the service's own contact number, its opening times and its current criteria.

What it never holds. The number is the service's own contact (a role or switchboard number, never a
mobile, DEC-1100), and nothing of a reporter or any other person: no name, no email, no mobile. A
field the system does not hold is None or empty, never made up. No case, patient or postcode is
read.

Read-only, in the bound tenant. A service of another tenant, an inactive one, and none are the same
NotFound. A role that is not a reader is NotAllowed (the route answers it as a 404).
"""

import re
from dataclasses import dataclass
from datetime import time
from typing import Final

from overwatch.application.actor import Actor, require_actor_in_bound_tenant
from overwatch.application.ports.outbound.clock import Clock
from overwatch.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from overwatch.application.use_cases.query_board import BoardEntry, QueryBoard, QueryBoardQuery
from overwatch.domain.codes import Role
from overwatch.domain.errors import NotAllowed, NotFound

READERS: Final = frozenset({Role.ADVISOR, Role.ADVISOR_V2, Role.ANALYTICS_USER})
"""Who reads a service's detail, and (DEC-1367) the day chart of the same page. The shift lead and
the clinical advisor have their own pages and are not named here."""


_UK_MOBILE: Final = re.compile(r"^07\d{9}$")


def is_personal_looking_mobile(number: str) -> bool:
    """A UK mobile number (07..., or +44 7... / 44 7...). The service contact is a role or
    switchboard number, never a person's mobile (DEC-1100 Q5), so a number of this shape is not
    shown as one (DEC-1367). Spaces, brackets and dashes do not hide it."""
    digits = re.sub(r"\D", "", number)
    if digits.startswith("44"):
        digits = "0" + digits[2:]
    return _UK_MOBILE.fullmatch(digits) is not None


@dataclass(frozen=True, slots=True)
class OpeningWindow:
    days: tuple[int, ...]
    """0 (Monday) to 6 (Sunday)."""
    all_day: bool
    start: time | None
    end: time | None


@dataclass(frozen=True, slots=True)
class ServiceDetail:
    entry: BoardEntry
    phone: str | None
    opening_hours: tuple[OpeningWindow, ...]
    accepts: tuple[str, ...] | None
    """The need codes the current criteria accept; None when the service has no current criteria."""
    excludes: tuple[str, ...] | None
    age_min: int | None
    age_max: int | None
    districts: tuple[str, ...]


class ReadServiceDetail:
    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._query_board = QueryBoard(uow_factory, clock)

    async def execute(self, actor: Actor, service_id: str) -> ServiceDetail:
        if actor.role not in READERS:
            raise NotAllowed("this role cannot read a service's detail")
        require_actor_in_bound_tenant(actor)
        # The board is read in its own unit of work, before this one opens: two units cannot be
        # open in one context (P06). An inactive service is not on it, so it is not found.
        board = await self._query_board.execute(QueryBoardQuery(actor))
        entry = next((item for item in board.entries if item.service_id == service_id), None)
        if entry is None:
            raise NotFound("no service with this id")
        async with self._uow_factory() as uow:
            profile = await uow.services.get(service_id)
            if profile is None:
                raise NotFound("no service with this id")
            held_phone = await uow.services.work_phone(service_id)
            criteria = await uow.criteria.current_for_service(service_id)
        phone = None if held_phone is None or is_personal_looking_mobile(held_phone) else held_phone
        windows = tuple(
            OpeningWindow(tuple(sorted(window.days)), window.all_day, window.start, window.end)
            for window in profile.available_times
        )
        if criteria is None:
            return ServiceDetail(entry, phone, windows, None, None, None, None, ())
        return ServiceDetail(
            entry=entry,
            phone=phone,
            opening_hours=windows,
            accepts=tuple(sorted(need.value for need in criteria.accepts)),
            excludes=tuple(sorted(need.value for need in criteria.excludes)),
            age_min=criteria.age_min,
            age_max=criteria.age_max,
            districts=tuple(sorted(criteria.districts)),
        )
