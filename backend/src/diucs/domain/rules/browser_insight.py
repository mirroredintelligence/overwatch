"""The browser's ui.* events, folded into daily counters (W9F, builds on O02, O03, O05 and O08).

Pure rules, no I/O. The browser sends a batch of events; the back end keeps no event. It reads each
one against the schema below (the same shape as frontend/lib/telemetry/schema.ts, so a value that
could carry free text is refused here too), and adds one to a counter of the day: which element was
used, which friction fired, which route was seen, how far a session got along a funnel, which
bucket a web vital fell in, and what a release did. A counter holds a count and the number of
sessions behind it, never a session id, a person, a typed value or a page text.

Sessions are counted once per group and day by a pseudonymous marker (`marker_key`): a keyed hash
of the session id with the group, the day and the tenant, so the counter can tell a second event of
the same session from a new session and the graph still holds no session id. Markers are removed
after two days.

The role is the caller's, from the verified token, never the browser's `user.role` claim.
"""

import hashlib
import hmac
import math
import re
from bisect import bisect_left
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Final

# The secret that keys the session markers (the secret-store seam; never in code or logs).
MARKER_SECRET: Final = "telemetry-markers"
# The markers of the day before are kept, older ones are removed (a marker is only ever asked for
# on its own day; the spare day is for a clock that is a little behind).
MARKER_KEEP_DAYS: Final = 1
# A batch is at most this many events (the BFF keeps the same ceiling).
MAX_BATCH_EVENTS: Final = 50
# A route a page-level event could not name.
UNKNOWN_ROUTE: Final = "/unknown"
# The histogram of a web vital has this many buckets (a measure's edges plus the overflow bucket).
BUCKET_COUNT: Final = 12
MAX_METRIC_VALUE: Final = 10_000_000.0

DEVICES: Final = ("phone", "tablet", "desktop")
APP_MODES: Final = ("browser", "installed")
FRICTION_KINDS: Final = (
    "rage",
    "dead",
    "error-click",
    "impatient",
    "u-turn",
    "thrash",
    "validation-loop",
    "abandonment",
    "hesitation",
    "missed-tap",
    "scroll-thrash",
    "stream-gap",
)
METRICS: Final = ("lcp", "inp", "cls")
PAGE_ELEMENT_ID: Final = "PAGE"

# The web-vitals "good" thresholds (observability.md, "Performance and responsiveness"). Each is a
# bucket edge, so a p75 on the budget reads as on it and not over it.
BUDGETS: Final[Mapping[str, float]] = MappingProxyType({"lcp": 2500.0, "inp": 200.0, "cls": 0.1})
# The upper edge of each bucket but the last (the overflow bucket). LCP and INP in milliseconds, CLS
# as a score.
EDGES: Final[Mapping[str, tuple[float, ...]]] = MappingProxyType(
    {
        "lcp": (500.0, 1000.0, 1500.0, 2000.0, 2500.0, 3000.0, 4000.0, 6000.0, 10000.0),
        "inp": (50.0, 100.0, 150.0, 200.0, 300.0, 500.0, 1000.0, 2000.0),
        "cls": (0.01, 0.05, 0.1, 0.15, 0.25, 0.5, 1.0),
    }
)

_SESSION_ID: Final = re.compile(r"[a-f0-9]{16,32}")
_RELEASE: Final = re.compile(r"\d+\.\d+\.\d+")
_ELEMENT_ID: Final = re.compile(r"[A-Z0-9]+(?:-[A-Z0-9]+)*")
_ROUTE: Final = re.compile(r"/(?:[a-z0-9\-]|/|\[[A-Za-z0-9]+\])*")
_ERROR_CODE: Final = re.compile(r"[A-Z0-9_-]{1,40}")
_MAX_ID_LENGTH: Final = 64
_MAX_ROUTE_LENGTH: Final = 120

_ELEMENT_EVENTS: Final = frozenset({"ui.click", "ui.input", "ui.toggle", "ui.chip"})
_EVENT_NAMES: Final = frozenset(
    {
        "ui.page_view",
        "ui.click",
        "ui.input",
        "ui.toggle",
        "ui.chip",
        "ui.submit",
        "ui.error_shown",
        "ui.friction",
        "ui.web_vital",
    }
)


@dataclass(frozen=True, slots=True)
class UiEvent:
    """One event that passed the schema. Only what a counter needs is kept."""

    name: str
    session_id: str
    device: str
    app_mode: str
    release: str
    route: str | None = None
    element_id: str | None = None
    kind: str | None = None
    metric: str | None = None
    reading: float | None = None


def _text(attributes: Mapping[str, object], key: str) -> str | None:
    value = attributes.get(key)
    return value if isinstance(value, str) else None


def _matching(value: str | None, pattern: re.Pattern[str], limit: int) -> str | None:
    if value is None or len(value) > limit or pattern.fullmatch(value) is None:
        return None
    return value


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0 or number > MAX_METRIC_VALUE:
        return None
    return number


def parse_event(name: str, attributes: Mapping[str, object]) -> UiEvent | None:
    """The event, or None when it breaks the schema. An attribute the schema does not name is left
    out, never kept; one it names that is present and wrong refuses the whole event."""
    if name not in _EVENT_NAMES:
        return None
    session = _matching(_text(attributes, "session.id"), _SESSION_ID, 32)
    release = _matching(_text(attributes, "release"), _RELEASE, 32)
    device = _text(attributes, "device.type")
    app_mode = _text(attributes, "app.mode") if "app.mode" in attributes else "browser"
    if session is None or release is None or device not in DEVICES or app_mode not in APP_MODES:
        return None
    assert device is not None and app_mode is not None
    route: str | None = None
    if "page.route" in attributes:
        route = _matching(_text(attributes, "page.route"), _ROUTE, _MAX_ROUTE_LENGTH)
        if route is None:
            return None
    element: str | None = None
    element_key = "form.id" if name == "ui.submit" else "element.id"
    if element_key in attributes:
        element = _matching(_text(attributes, element_key), _ELEMENT_ID, _MAX_ID_LENGTH)
        if element is None:
            return None
    kind: str | None = None
    metric: str | None = None
    reading: float | None = None
    if name == "ui.page_view" and route is None:
        return None
    if (name in _ELEMENT_EVENTS or name in {"ui.submit", "ui.friction"}) and element is None:
        return None
    if (
        name == "ui.error_shown"
        and "error.code" in attributes
        and _matching(_text(attributes, "error.code"), _ERROR_CODE, 40) is None
    ):
        return None
    if name == "ui.friction":
        kind = _text(attributes, "kind")
        if kind not in FRICTION_KINDS:
            return None
    if name == "ui.web_vital":
        metric = _text(attributes, "metric")
        reading = _number(attributes.get("reading"))
        if metric not in METRICS or reading is None:
            return None
    return UiEvent(
        name=name,
        session_id=session,
        device=device,
        app_mode=app_mode,
        release=release,
        route=route,
        element_id=element,
        kind=kind,
        metric=metric,
        reading=reading,
    )


# ---- the histogram -------------------------------------------------------------------------------


def bucket_of(measure: str, value: float) -> int:
    """The bucket a value falls in: the first whose upper edge is at or above it, or the overflow
    bucket. A value on an edge is in that edge's bucket."""
    return bisect_left(EDGES[measure], value)


def percentile(buckets: Sequence[int], measure: str, q: float) -> float | None:
    """The q-th percentile as the upper edge of the bucket that holds it (a bound that never reads
    better than the data), or None with no samples. The overflow bucket reports the last edge."""
    total = sum(buckets)
    if total <= 0:
        return None
    edges = EDGES[measure]
    rank = math.ceil(q * total)
    seen = 0
    for index, count in enumerate(buckets):
        seen += count
        if seen >= rank:
            return edges[min(index, len(edges) - 1)]
    return edges[-1]


# ---- the funnels the browser can see -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UiFunnelStep:
    step: str
    routes: frozenset[str]


def _step(step: str, *routes: str) -> UiFunnelStep:
    return UiFunnelStep(step, frozenset(routes))


# The steps of each funnel that a page view shows, in order. The spec's funnels (FUNNELS in
# telemetry_insights) have steps that are not screens (a text delivered, a booking confirmed); those
# are not here, and nothing stands in for them. A session is counted at the furthest step it
# reached (a step shown is a screen reached, not a task finished).
BROWSER_FUNNELS: Final[Mapping[str, tuple[UiFunnelStep, ...]]] = MappingProxyType(
    {
        "reporter-set-up": (
            _step("Set-up opened", "/setup"),
            _step("Home-screen guide viewed", "/setup/home-screen"),
            _step("Notification screen viewed", "/setup/notifications"),
            _step("PIN screen viewed", "/setup/pin"),
            _step("Set-up finished", "/setup/all-set", "/setup/done"),
        ),
        "daily-capacity-loop": (
            _step("Update screen opened", "/app/respond/[serviceId]", "/l/[token]"),
            _step("Update sent", "/app/respond/[serviceId]/thanks", "/l/[token]/thanks"),
        ),
        "advisor-call": (
            _step("Case opened", "/advisor/case/[ref]"),
            _step("Options viewed", "/advisor/case/[ref]/options"),
            _step("Outcome screen viewed", "/advisor/case/[ref]/finish"),
        ),
        "registration": (
            _step("Started", "/register/[id]/start"),
            _step("Organisation screen viewed", "/register/[id]/organisation"),
            _step("Location screen viewed", "/register/[id]/location"),
            _step("Service screen viewed", "/register/[id]/service"),
            _step("Capacity reporting screen viewed", "/register/[id]/reporting"),
            _step("Review screen viewed", "/register/[id]/review"),
            _step("Submitted", "/register/[id]/submitted"),
        ),
        "criteria-review": (
            _step("Criteria opened", "/criteria/[serviceId]"),
            _step("Second approval screen viewed", "/criteria/[serviceId]/approve"),
        ),
    }
)
BROWSER_FUNNEL_LABELS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "reporter-set-up": "Reporter set-up",
        "daily-capacity-loop": "Daily capacity update",
        "advisor-call": "Advisor call",
        "registration": "Registration",
        "criteria-review": "Criteria review",
    }
)

_STEP_OF_ROUTE: Final[Mapping[str, tuple[tuple[str, int], ...]]] = MappingProxyType(
    {
        route: tuple(
            (funnel, index)
            for funnel, steps in BROWSER_FUNNELS.items()
            for index, step in enumerate(steps)
            if route in step.routes
        )
        for route in {
            route for steps in BROWSER_FUNNELS.values() for s in steps for route in s.routes
        }
    }
)


# ---- folding a batch -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UsageTally:
    element_id: str
    role: str
    device: str
    session_id: str
    count: int


@dataclass(frozen=True, slots=True)
class FrictionTally:
    element_id: str
    kind: str
    route: str
    role: str
    device: str
    session_id: str
    count: int


@dataclass(frozen=True, slots=True)
class RouteTally:
    route: str
    role: str
    device: str
    session_id: str
    errors: int


@dataclass(frozen=True, slots=True)
class FunnelTally:
    funnel: str
    role: str
    channel: str
    device: str
    session_id: str
    top: int


@dataclass(frozen=True, slots=True)
class MeasureTally:
    measure: str
    route: str
    device: str
    release: str
    session_id: str
    buckets: tuple[int, ...]
    samples: int


@dataclass(frozen=True, slots=True)
class ReleaseTally:
    release: str
    session_id: str
    interactions: int
    friction: int
    errors: int
    views: int


@dataclass(frozen=True, slots=True)
class BatchTally:
    usage: tuple[UsageTally, ...] = ()
    friction: tuple[FrictionTally, ...] = ()
    routes: tuple[RouteTally, ...] = ()
    funnels: tuple[FunnelTally, ...] = ()
    measures: tuple[MeasureTally, ...] = ()
    releases: tuple[ReleaseTally, ...] = ()


def fold(role: str, events: Sequence[UiEvent]) -> BatchTally:
    """The counters one batch adds. Interactions are clicks and submits (a chip or a switch fires a
    click as well, so counting both would count one tap twice; typing is not an interaction)."""
    usage: dict[tuple[str, str, str], int] = {}
    friction: dict[tuple[str, str, str, str, str], int] = {}
    routes: dict[tuple[str, str, str], int] = {}
    funnels: dict[tuple[str, str, str, str], int] = {}
    measures: dict[tuple[str, str, str, str, str], tuple[list[int], int]] = {}
    releases: dict[tuple[str, str], list[int]] = {}

    for item in events:
        counters = releases.setdefault((item.release, item.session_id), [0, 0, 0, 0])
        if item.name in {"ui.click", "ui.submit"} and item.element_id is not None:
            key = (item.element_id, item.device, item.session_id)
            usage[key] = usage.get(key, 0) + 1
            counters[0] += 1
        elif item.name == "ui.friction" and item.element_id is not None and item.kind is not None:
            route = ""
            if item.element_id == PAGE_ELEMENT_ID:
                route = item.route or UNKNOWN_ROUTE
            fkey = (item.element_id, item.kind, route, item.device, item.session_id)
            friction[fkey] = friction.get(fkey, 0) + 1
            counters[1] += 1
        elif item.name == "ui.error_shown":
            ekey = (item.route or UNKNOWN_ROUTE, item.device, item.session_id)
            routes[ekey] = routes.get(ekey, 0) + 1
            counters[2] += 1
        elif item.name == "ui.page_view" and item.route is not None:
            vkey = (item.route, item.device, item.session_id)
            routes.setdefault(vkey, 0)
            counters[3] += 1
            channel = "app" if item.app_mode == "installed" else "browser"
            for funnel, index in _STEP_OF_ROUTE.get(item.route, ()):
                fnkey = (funnel, channel, item.device, item.session_id)
                funnels[fnkey] = max(funnels.get(fnkey, -1), index)
        elif item.name == "ui.web_vital" and item.metric is not None and item.reading is not None:
            mkey = (
                item.metric,
                item.route or UNKNOWN_ROUTE,
                item.device,
                item.release,
                item.session_id,
            )
            buckets, samples = measures.get(mkey, ([0] * BUCKET_COUNT, 0))
            buckets[bucket_of(item.metric, item.reading)] += 1
            measures[mkey] = (buckets, samples + 1)

    return BatchTally(
        usage=tuple(
            UsageTally(element, role, device, session, count)
            for (element, device, session), count in sorted(usage.items())
        ),
        friction=tuple(
            FrictionTally(element, kind, route, role, device, session, count)
            for (element, kind, route, device, session), count in sorted(friction.items())
        ),
        routes=tuple(
            RouteTally(route, role, device, session, errors)
            for (route, device, session), errors in sorted(routes.items())
        ),
        funnels=tuple(
            FunnelTally(funnel, role, channel, device, session, top)
            for (funnel, channel, device, session), top in sorted(funnels.items())
        ),
        measures=tuple(
            MeasureTally(measure, route, device, release, session, tuple(buckets), samples)
            for (measure, route, device, release, session), (buckets, samples) in sorted(
                measures.items()
            )
        ),
        releases=tuple(
            ReleaseTally(release, session, c[0], c[1], c[2], c[3])
            for (release, session), c in sorted(releases.items())
        ),
    )


def marker_key(
    secret: bytes,
    tenant: str,
    day: date,
    family: str,
    dims: Sequence[str],
    session_id: str,
) -> str:
    """The pseudonymous marker of a session in one group on one day: a keyed hash, so the graph
    never holds the session id and the marker cannot be joined to the session of a support code.
    The parts are joined with a separator no part can hold, so two groups never share a marker."""
    message = "\x1f".join([tenant, day.isoformat(), family, *dims, session_id])
    return hmac.new(secret, message.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
