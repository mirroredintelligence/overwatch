"""next_due has a due instant for every valid profile, so a report's echo always has a next prompt.

A profile's windows always have a day and a timed or all-day shape (AvailableTime checks that),
and the search covers every weekday, so a due instant after now exists. This test checks that for
generated profiles, across cadences, all-day and overnight windows, and both clock changes of 2026.
"""

from datetime import UTC, datetime, timedelta

from hypothesis import given
from hypothesis import strategies as st

from diucs.domain.codes import Cadence, Channel, Measure, ServiceCategory
from diucs.domain.model.service import AvailableTime, ServiceProfile
from diucs.domain.rules.schedule import next_due

TIMES = st.times().map(lambda t: t.replace(second=0, microsecond=0))


@st.composite
def windows(draw: st.DrawFn) -> AvailableTime:
    days = draw(st.frozensets(st.integers(min_value=0, max_value=6), min_size=1))
    if draw(st.booleans()):
        return AvailableTime(days=days, all_day=True, start=None, end=None)
    start = draw(TIMES)
    end = draw(TIMES.filter(lambda t: t != start))
    return AvailableTime(days=days, all_day=False, start=start, end=end)


@st.composite
def profiles(draw: st.DrawFn) -> ServiceProfile:
    available = draw(st.lists(windows(), min_size=1, max_size=3))
    cadence = draw(st.sampled_from(list(Cadence)))
    return ServiceProfile(
        id="svc-generated",
        name="Generated",
        category=ServiceCategory.INPATIENT_BEDS,
        measure=Measure.FREE_BEDS,
        unit_label="beds",
        established_capacity=12,
        can_exceed_established=False,
        usual_range=(0, 12),
        cadence=cadence,
        available_times=tuple(available),
        channel=Channel.TEXT,
    )


NOWS = st.datetimes(
    min_value=datetime(2026, 3, 1),
    max_value=datetime(2026, 11, 30),
    timezones=st.just(UTC),
)


@given(profile=profiles(), now=NOWS)
def test_every_valid_profile_has_a_next_due_after_any_instant(
    profile: ServiceProfile, now: datetime
) -> None:
    due = next_due(profile, now)

    assert due is not None
    assert due > now
    assert due <= now + timedelta(days=8)
