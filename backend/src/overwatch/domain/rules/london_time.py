"""Local time helpers. Domain times are UTC; schedules are computed in the tenant's time zone,
which is Europe/London for every tenant today (TEN-065, DEC-136 item 13).

The zone is a value that the rules take as an argument, and none of them looks one up. A tenant (and
a network) stores a zone name that is validated against an allow-list, and `zone_named` makes the
`ZoneInfo` from it; the allow-list is enforced there and on the tenant record, so the rules accept
any `ZoneInfo` and a test can show the zone is really used. Every function defaults to London, so a
caller that has not been given its tenant's zone yet behaves as it always did (a ratchet in
`tests/unit/domain/rules/test_zone_threading.py` lists those callers). `to_london`, `london_to_utc`
are the London case of `to_local`, `local_to_utc`, kept for those callers.

Clock changes (the same rule in every zone, shown for Europe/London):
- Spring gap, 2026-03-29 01:00 to 02:00 does not exist. A local time in the gap is shifted
  forward by the gap length (zoneinfo with fold=0 keeps the pre-change offset, which does this).
- Autumn fold, 2026-10-25 01:00 to 02:00 happens twice. The first occurrence (BST) is used,
  which is also zoneinfo with fold=0.
"""

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from diucs.domain.model.tenant import check_time_zone

LONDON = ZoneInfo("Europe/London")


def zone_named(name: object) -> ZoneInfo:
    """The zone of a stored zone name. A name that is not on the allow-list (only Europe/London
    today) or not a `str` is refused as `ValidationFailed("time_zone")`, with no value in it."""
    return ZoneInfo(check_time_zone(name))


def require_zone(zone: object) -> ZoneInfo:
    """The zone, when it is exactly a `ZoneInfo`. A zone name, `None`, `timezone.utc` and anything
    else are refused: a rule never guesses a zone from text."""
    if type(zone) is not ZoneInfo:
        raise TypeError("a ZoneInfo is required")
    return zone


def _require_aware(dt: datetime) -> None:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware (UTC)")


def to_local(dt: datetime, zone: ZoneInfo = LONDON) -> datetime:
    """Return the same instant as a wall-clock datetime in `zone`. Naive input is a bug."""
    zone = require_zone(zone)
    _require_aware(dt)
    return dt.astimezone(zone)


def local_to_utc(d: date, t: time, zone: ZoneInfo = LONDON) -> datetime:
    """Return the UTC instant for a local date and time of day in `zone`.

    The local wall-clock value is kept across clock changes, so 10:00 London is 09:00Z in
    summer and 10:00Z in winter. Gap times are shifted forward; fold times take the first
    occurrence.
    """
    zone = require_zone(zone)
    if t.tzinfo is not None:
        raise ValueError("time of day must be naive local time")
    local = datetime.combine(d, t).replace(tzinfo=zone, fold=0)
    return local.astimezone(UTC)


def to_london(dt: datetime) -> datetime:
    """Return the same instant as a London wall-clock datetime. Naive input is a bug."""
    return to_local(dt, LONDON)


def london_to_utc(d: date, t: time) -> datetime:
    """Return the UTC instant for a London local date and time of day (`local_to_utc` in London)."""
    return local_to_utc(d, t, LONDON)


def format_hhmm(dt: datetime, zone: ZoneInfo = LONDON) -> str:
    """Return the wall-clock time in `zone` as HH:MM, for messages and the wall board."""
    return to_local(dt, zone).strftime("%H:%M")


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def format_stamp(dt: datetime, zone: ZoneInfo = LONDON) -> str:
    """Return the local day, month and time as "23 Oct 08:15": the full date of a figure, so that
    a figure from another day cannot read as the current one (DEC-115 item 11)."""
    local = to_local(dt, zone)
    return f"{local.day} {_MONTHS[local.month - 1]} {local.strftime('%H:%M')}"
