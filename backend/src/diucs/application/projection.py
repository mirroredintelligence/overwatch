"""Rows, bodies and the statement check for the network projection (TEN-052).

The allowlist is defined once, in `domain/rules/projection.py`. This module turns a DTO into what is
written and sent, and reads it back, so that nothing outside the allowlist can pass through:

- `to_rows`: the property rows of a DTO, with exactly the stored properties of each label.
- `to_body` and `from_body`: the flat body of a projection message (snake_case DTO field names,
  location fields inline, opening hours as window strings, timestamps ISO 8601 with `Z`).
  `from_body` accepts exactly the keys of its kind and runs the DTO's own checks again, so a body
  built by hand cannot bypass the guard.
- `check_network_write_statement`: a conservative parse of a Cypher statement that refuses anything
  that could write a property or a label the allowlist does not name (`SET n += $map` among them).
  It fails closed: a statement it cannot read is `unparseable`.

Imports the domain only. Nothing here reads a clock, a tenant or a store, and nothing logs a value.
"""

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from enum import StrEnum
from typing import Any, Final

from diucs.domain.codes import Cadence, Measure, NeedCategory, ServiceCategory
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.network import DirectorySource, GrantScope
from diucs.domain.rules import projection as allowlist
from diucs.domain.rules.projection import (
    CapacityProjection,
    CriteriaProjection,
    LocationProjection,
    OpeningHourProjection,
    ServiceProjection,
)

type ProjectionValue = str | int | float | bool | None | tuple[str, ...]
type Projection = ServiceProjection | CapacityProjection | CriteriaProjection
type RowValue = str | int | float | bool | None | list[Any] | datetime | date | time

BODY_MESSAGE: Final = "the projection body is not valid"
WINDOW_MESSAGE: Final = "is not a valid opening window"
OPENING_HOURS_KEY: Final = "opening_hours"
ALL_DAY_WORD: Final = "all-day"

_INSTANT: Final = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z"
)
_DATE: Final = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_CLOCK: Final = re.compile(r"[0-9]{2}:[0-9]{2}:[0-9]{2}")
_DAY: Final = re.compile(r"[0-6]")

# ---------------------------------------------------------------- rows


@dataclass(frozen=True, slots=True)
class ProjectionRow:
    """One node to write: its network label and its properties, keyed by stored property name."""

    label: str
    params: Mapping[str, RowValue]


def _stored(value: object) -> RowValue:
    """A value in the form the store holds: an enum as its code, a sequence as a list."""
    if isinstance(value, StrEnum):
        return str(value.value)
    if isinstance(value, tuple):
        return [_stored(item) for item in value]
    return value  # type: ignore[return-value]


def _row(label: str, source: object) -> ProjectionRow:
    return ProjectionRow(
        label,
        {
            spec.prop: _stored(getattr(source, spec.dto_field))
            for spec in allowlist.ALLOWLIST[label]
        },
    )


def to_rows(dto: Projection) -> list[ProjectionRow]:
    """The rows of a DTO. A service gives its own row, its location row (if any) and one row per
    opening hour, in order; the children carry no parent id (the repository keys them by their
    parent). Every key of the label is always present, an absent value as `None`."""
    if type(dto) is ServiceProjection:
        rows = [_row(ServiceProjection.label, dto)]
        if dto.location is not None:
            rows.append(_row(LocationProjection.label, dto.location))
        rows.extend(_row(OpeningHourProjection.label, hour) for hour in dto.opening_hours)
        return rows
    if type(dto) is CapacityProjection:
        return [_row(CapacityProjection.label, dto)]
    if type(dto) is CriteriaProjection:
        return [_row(CriteriaProjection.label, dto)]
    raise ValidationFailed("projection", "is not a projection")


# ---------------------------------------------------------------- windows


def format_window(hour: OpeningHourProjection) -> str:
    """`<days csv>|<HH:MM:SS>|<HH:MM:SS>`, or `<days csv>|all-day`."""
    days = ",".join(str(day) for day in hour.days)
    if hour.all_day:
        return f"{days}|{ALL_DAY_WORD}"
    if hour.start is None or hour.end is None:
        raise ValidationFailed(OPENING_HOURS_KEY, WINDOW_MESSAGE)
    return f"{days}|{hour.start.strftime('%H:%M:%S')}|{hour.end.strftime('%H:%M:%S')}"


def _clock(text: str) -> time:
    if _CLOCK.fullmatch(text) is None:
        raise ValidationFailed(OPENING_HOURS_KEY, WINDOW_MESSAGE)
    try:
        return time.fromisoformat(text)
    except ValueError:
        raise ValidationFailed(OPENING_HOURS_KEY, WINDOW_MESSAGE) from None


def parse_window(text: str, position: int) -> OpeningHourProjection:
    """The opening hour a window string names, at `position`. Anything but the documented form,
    including days out of order or repeated, is refused (the refusal never echoes the text)."""
    if type(text) is not str:
        raise ValidationFailed(OPENING_HOURS_KEY, WINDOW_MESSAGE)
    parts = text.split("|")
    days_text = parts[0].split(",")
    if not all(_DAY.fullmatch(day) for day in days_text):
        raise ValidationFailed(OPENING_HOURS_KEY, WINDOW_MESSAGE)
    days = tuple(int(day) for day in days_text)
    if list(days) != sorted(set(days)):
        raise ValidationFailed(OPENING_HOURS_KEY, WINDOW_MESSAGE)
    if len(parts) == 2 and parts[1] == ALL_DAY_WORD:
        return OpeningHourProjection(
            position=position, days=days, all_day=True, start=None, end=None
        )
    if len(parts) != 3:  # noqa: PLR2004
        raise ValidationFailed(OPENING_HOURS_KEY, WINDOW_MESSAGE)
    return OpeningHourProjection(
        position=position, days=days, all_day=False, start=_clock(parts[1]), end=_clock(parts[2])
    )


# ---------------------------------------------------------------- bodies


def _body_value(value: object) -> ProjectionValue:
    if isinstance(value, StrEnum):
        return str(value.value)
    if type(value) is datetime:
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if type(value) is date:
        return value.isoformat()
    if isinstance(value, tuple):
        return tuple(str(_body_value(item)) for item in value)
    return value  # type: ignore[return-value]


def _body_of(label: str, source: object | None, body: dict[str, ProjectionValue]) -> None:
    for spec in allowlist.ALLOWLIST[label]:
        body[spec.dto_field] = (
            None if source is None else _body_value(getattr(source, spec.dto_field))
        )


def to_body(dto: Projection) -> dict[str, ProjectionValue]:
    """The flat body of a projection message: the DTO field names as keys, every key always
    present. The location fields are inline (all `None` for a service with no location) and the
    opening hours are a tuple of window strings."""
    body: dict[str, ProjectionValue] = {}
    if type(dto) is ServiceProjection:
        _body_of(ServiceProjection.label, dto, body)
        _body_of(LocationProjection.label, dto.location, body)
        body[OPENING_HOURS_KEY] = tuple(format_window(hour) for hour in dto.opening_hours)
        return body
    if type(dto) is CapacityProjection:
        _body_of(CapacityProjection.label, dto, body)
        return body
    if type(dto) is CriteriaProjection:
        _body_of(CriteriaProjection.label, dto, body)
        return body
    raise ValidationFailed("projection", "is not a projection")


def body_keys(kind: GrantScope) -> frozenset[str]:
    """The keys a body of this kind holds, exactly."""
    _scope(kind)
    if kind is GrantScope.DIRECTORY:
        names = {spec.dto_field for spec in allowlist.ALLOWLIST[ServiceProjection.label]}
        names |= {spec.dto_field for spec in allowlist.ALLOWLIST[LocationProjection.label]}
        return frozenset(names | {OPENING_HOURS_KEY})
    label = CapacityProjection.label if kind is GrantScope.CAPACITY else CriteriaProjection.label
    return frozenset(spec.dto_field for spec in allowlist.ALLOWLIST[label])


def _scope(kind: object) -> GrantScope:
    if type(kind) is not GrantScope:
        raise ValidationFailed("kind", "is not a projection kind")
    return kind


def _wrong(key: str) -> ValidationFailed:
    return ValidationFailed("body", f"{key} has the wrong type or an unknown value")


def _text(key: str, value: object) -> str:
    if type(value) is not str:
        raise _wrong(key)
    return value


def _opt_text(key: str, value: object) -> str | None:
    return None if value is None else _text(key, value)


def _whole(key: str, value: object) -> int:
    if type(value) is not int:
        raise _wrong(key)
    return value


def _opt_whole(key: str, value: object) -> int | None:
    return None if value is None else _whole(key, value)


def _flag(key: str, value: object) -> bool:
    if type(value) is not bool:
        raise _wrong(key)
    return value


def _real(key: str, value: object) -> float | None:
    if value is None:
        return None
    if type(value) is not float:
        raise _wrong(key)
    return value


def _code[E: StrEnum](key: str, value: object, kind: type[E]) -> E:
    if type(value) is not str:
        raise _wrong(key)
    try:
        return kind(value)
    except ValueError:
        raise _wrong(key) from None


def _instant(key: str, value: object) -> datetime:
    if type(value) is not str or _INSTANT.fullmatch(value) is None:
        raise _wrong(key)
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise _wrong(key) from None


def _opt_instant(key: str, value: object) -> datetime | None:
    return None if value is None else _instant(key, value)


def _day(key: str, value: object) -> date:
    if type(value) is not str or _DATE.fullmatch(value) is None:
        raise _wrong(key)
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise _wrong(key) from None


def _texts(key: str, value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple) or not all(type(item) is str for item in value):
        raise _wrong(key)
    return tuple(value)


def _codes[E: StrEnum](key: str, value: object, kind: type[E]) -> tuple[E, ...]:
    return tuple(_code(key, item, kind) for item in _texts(key, value))


def _service_from(body: Mapping[str, object]) -> ServiceProjection:
    location_keys = ("location_name", "postal_district", "city", "latitude", "longitude")
    location: LocationProjection | None = None
    if any(body[key] is not None for key in location_keys):
        location = LocationProjection(
            location_name=_text("location_name", body["location_name"]),
            postal_district=_opt_text("postal_district", body["postal_district"]),
            city=_opt_text("city", body["city"]),
            latitude=_real("latitude", body["latitude"]),
            longitude=_real("longitude", body["longitude"]),
        )
    windows = _texts(OPENING_HOURS_KEY, body[OPENING_HOURS_KEY])
    return ServiceProjection(
        source_service_id=_text("source_service_id", body["source_service_id"]),
        source_version=_whole("source_version", body["source_version"]),
        service_name=_text("service_name", body["service_name"]),
        category=_code("category", body["category"], ServiceCategory),
        active=_flag("active", body["active"]),
        source=_code("source", body["source"], DirectorySource),
        contact_label=_opt_text("contact_label", body["contact_label"]),
        contact_phone=_opt_text("contact_phone", body["contact_phone"]),
        location=location,
        opening_hours=tuple(parse_window(text, index) for index, text in enumerate(windows)),
    )


def _capacity_from(body: Mapping[str, object]) -> CapacityProjection:
    return CapacityProjection(
        source_service_id=_text("source_service_id", body["source_service_id"]),
        source_version=_whole("source_version", body["source_version"]),
        measure=_code("measure", body["measure"], Measure),
        unit_label=_text("unit_label", body["unit_label"]),
        established_capacity=_whole("established_capacity", body["established_capacity"]),
        can_exceed_established=_flag("can_exceed_established", body["can_exceed_established"]),
        limited_level_percent=_whole("limited_level_percent", body["limited_level_percent"]),
        cadence=_code("cadence", body["cadence"], Cadence),
        suspended=_flag("suspended", body["suspended"]),
        report_id=_opt_text("report_id", body["report_id"]),
        reported_at=_opt_instant("reported_at", body["reported_at"]),
        value=_opt_whole("value", body["value"]),
        confirmed_since=_whole("confirmed_since", body["confirmed_since"]),
        reply_window_minutes=_whole("reply_window_minutes", body["reply_window_minutes"]),
        stale_warning_hours=_whole("stale_warning_hours", body["stale_warning_hours"]),
        valid_until=_opt_instant("valid_until", body["valid_until"]),
    )


def _criteria_from(body: Mapping[str, object]) -> CriteriaProjection:
    return CriteriaProjection(
        source_criteria_id=_text("source_criteria_id", body["source_criteria_id"]),
        source_service_id=_text("source_service_id", body["source_service_id"]),
        version=_whole("version", body["version"]),
        age_min=_whole("age_min", body["age_min"]),
        age_max=_opt_whole("age_max", body["age_max"]),
        districts=_texts("districts", body["districts"]),
        accepts=_codes("accepts", body["accepts"], NeedCategory),
        excludes=_codes("excludes", body["excludes"], NeedCategory),
        review_by=_day("review_by", body["review_by"]),
    )


_FROM: Final[Mapping[GrantScope, Callable[[Mapping[str, object]], Projection]]] = {
    GrantScope.DIRECTORY: _service_from,
    GrantScope.CAPACITY: _capacity_from,
    GrantScope.CRITERIA: _criteria_from,
}


def from_body(kind: GrantScope, body: Mapping[str, object]) -> Projection:
    """The DTO a body holds. The body must have exactly the keys of its kind: a missing key, an
    extra key or a value of the wrong type is `ValidationFailed("body", ...)`, naming the key's
    position or a known field and never echoing a value. The DTO's own checks then run again."""
    expected = body_keys(kind)  # refuses a kind that is not a grant scope
    if not isinstance(body, Mapping) or not all(type(key) is str for key in body):
        raise ValidationFailed("body", BODY_MESSAGE)
    for position, key in enumerate(sorted(body)):
        if key not in expected:
            raise ValidationFailed("body", f"unexpected key at position {position}")
    for key in sorted(expected):
        if key not in body:
            raise ValidationFailed("body", f"missing key {key}")
    return _FROM[kind](body)


# ---------------------------------------------------------------- the statement check

UNPARSEABLE: Final = "unparseable"

_WRITE_CLAUSES: Final = frozenset({"MERGE", "CREATE", "SET", "DELETE", "REMOVE", "CALL", "FOREACH"})
_SINGLE_CLAUSES: Final = frozenset(
    {
        "MATCH",
        "MERGE",
        "CREATE",
        "SET",
        "WITH",
        "UNWIND",
        "RETURN",
        "WHERE",
        "DELETE",
        "REMOVE",
        "CALL",
        "FOREACH",
        "UNION",
        "SKIP",
        "LIMIT",
    }
)
_OPENERS: Final = {"(": ")", "[": "]", "{": "}"}
_CLOSERS: Final = frozenset(_OPENERS.values())
_TWO_CHAR: Final = frozenset({"+=", "<>", "<=", ">=", "->", "<-", "..", "=~"})
_ONE_CHAR: Final = frozenset("()[]{},:=.-+*/%^<>|&")
_WORD_START: Final = re.compile(r"[A-Za-z_]")
_WORD: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_PARAM: Final = re.compile(r"\$[A-Za-z_0-9]+")
_NUMBER: Final = re.compile(r"[0-9]+(?:\.[0-9]+)?")
_ENDS: Final = frozenset({")", "]", "}"})


class _Unparseable(Exception):
    """Internal: the statement cannot be read. Never leaves this module."""


@dataclass(frozen=True, slots=True)
class _Token:
    kind: str  # word, quoted, param, number, string, symbol
    text: str

    @property
    def upper(self) -> str:
        return self.text.upper() if self.kind == "word" else ""

    def is_symbol(self, *symbols: str) -> bool:
        return self.kind == "symbol" and self.text in symbols


def _skip_string(text: str, start: int) -> int:
    quote = text[start]
    i = start + 1
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == quote:
            return i + 1
        i += 1
    raise _Unparseable


def _lex(cypher: str) -> tuple[list[_Token], bool]:
    """Tokens of the statement with comments removed and string literals masked, and whether a
    backtick was seen. A comment or string that is not closed is unparseable."""
    tokens: list[_Token] = []
    backticks = False
    text = cypher.rstrip()
    if text.endswith(";"):
        text = text[:-1]
    i = 0
    while i < len(text):
        char = text[i]
        pair = text[i : i + 2]
        if char.isspace():
            i += 1
        elif pair == "//":
            end = text.find("\n", i)
            i = len(text) if end == -1 else end + 1
        elif pair == "/*":
            end = text.find("*/", i + 2)
            if end == -1:
                raise _Unparseable
            i = end + 2
        elif char in "'\"":
            i = _skip_string(text, i)
            tokens.append(_Token("string", "''"))
        elif char == "`":
            end = text.find("`", i + 1)
            if end == -1:
                raise _Unparseable
            backticks = True
            tokens.append(_Token("quoted", text[i : end + 1]))
            i = end + 1
        elif char == "$":
            match = _PARAM.match(text, i)
            if match is None:
                raise _Unparseable
            tokens.append(_Token("param", match.group()))
            i = match.end()
        elif _WORD_START.match(char):
            match = _WORD.match(text, i)
            assert match is not None
            tokens.append(_Token("word", match.group()))
            i = match.end()
        elif char.isdigit():
            match = _NUMBER.match(text, i)
            assert match is not None
            tokens.append(_Token("number", match.group()))
            i = match.end()
        elif pair in _TWO_CHAR:
            tokens.append(_Token("symbol", pair))
            i += 2
        elif char in _ONE_CHAR:
            tokens.append(_Token("symbol", char))
            i += 1
        else:
            raise _Unparseable
    return tokens, backticks


def _check_shape(tokens: Sequence[_Token]) -> None:
    """Balanced brackets, and a statement that does not stop in the middle of an expression."""
    stack: list[str] = []
    for token in tokens:
        if token.is_symbol(*_OPENERS):
            stack.append(_OPENERS[token.text])
        elif token.is_symbol(*_CLOSERS) and (not stack or stack.pop() != token.text):
            raise _Unparseable
    last = tokens[-1]
    ends_cleanly = last.kind in {"word", "quoted", "param", "number", "string"} or last.is_symbol(
        *_ENDS
    )
    if stack or not ends_cleanly:
        raise _Unparseable


@dataclass(slots=True)
class _Clause:
    name: str
    tokens: list[_Token]


def _clause_start(tokens: Sequence[_Token], i: int) -> tuple[str, int] | None:
    """The clause that starts at token i (at depth zero), and how many tokens its keywords use.

    `ON CREATE SET` and `ON MATCH SET` need no case of their own: they read as an empty CREATE or
    MATCH clause followed by a SET, and that SET is checked like any other. `CALL` and `FOREACH`
    are refused by `_Check.scan`, wherever they stand."""
    token = tokens[i]
    if token.kind != "word" or (i > 0 and tokens[i - 1].is_symbol(".")):
        return None
    word = token.upper
    following = tokens[i + 1].upper if i + 1 < len(tokens) else ""
    if word == "OPTIONAL" and following == "MATCH":
        return "MATCH", 2
    if word == "DETACH" and following == "DELETE":
        return "DELETE", 2
    if word == "ORDER" and following == "BY":
        return "ORDER", 2
    if word in _SINGLE_CLAUSES:
        return word, 1
    return None


def _clauses(tokens: Sequence[_Token]) -> list[_Clause]:
    clauses: list[_Clause] = []
    depth = 0
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if depth == 0:
            start = _clause_start(tokens, i)
            if start is not None:
                clauses.append(_Clause(start[0], []))
                i += start[1]
                continue
            if not clauses:
                raise _Unparseable  # the statement does not begin with a clause
        if token.is_symbol(*_OPENERS):
            depth += 1
        elif token.is_symbol(*_CLOSERS):
            depth -= 1
        clauses[-1].tokens.append(token)
        i += 1
    return clauses


def _split_commas(tokens: Sequence[_Token]) -> list[list[_Token]]:
    items: list[list[_Token]] = [[]]
    depth = 0
    for token in tokens:
        if token.is_symbol(*_OPENERS):
            depth += 1
        elif token.is_symbol(*_CLOSERS):
            depth -= 1
        if depth == 0 and token.is_symbol(","):
            items.append([])
        else:
            items[-1].append(token)
    return items


def _matching(tokens: Sequence[_Token], start: int) -> int:
    depth = 0
    for i in range(start, len(tokens)):
        if tokens[i].is_symbol(*_OPENERS):
            depth += 1
        elif tokens[i].is_symbol(*_CLOSERS):
            depth -= 1
            if depth == 0:
                return i
    raise _Unparseable


@dataclass(frozen=True, slots=True)
class _Node:
    var: str | None
    labels: tuple[str, ...]
    keys: tuple[str, ...]
    parameter_map: bool


@dataclass(frozen=True, slots=True)
class _Relationship:
    var: str | None
    types: tuple[str, ...]
    has_properties: bool


def _map_keys(tokens: Sequence[_Token]) -> tuple[str, ...]:
    """The keys of a `{key: value, ...}` map given the tokens between the braces."""
    keys: list[str] = []
    for item in _split_commas(tokens):
        if not item and not keys:
            continue
        if len(item) < 3 or item[0].kind != "word" or not item[1].is_symbol(":"):  # noqa: PLR2004
            raise _Unparseable
        keys.append(item[0].text)
    return tuple(keys)


def _properties(tokens: Sequence[_Token], position: int) -> tuple[tuple[str, ...], bool]:
    """The map or parameter that ends a node or relationship body, from `position`."""
    rest = tokens[position:]
    if not rest:
        return (), False
    if len(rest) == 1 and rest[0].kind == "param":
        return (), True
    if rest[0].is_symbol("{") and _matching(rest, 0) == len(rest) - 1:
        return _map_keys(rest[1:-1]), False
    raise _Unparseable


def _node(body: Sequence[_Token]) -> _Node:
    i = 0
    var: str | None = None
    if i < len(body) and body[i].kind == "word":
        var = body[i].text
        i += 1
    labels: list[str] = []
    while i + 1 < len(body) and body[i].is_symbol(":") and body[i + 1].kind == "word":
        labels.append(body[i + 1].text)
        i += 2
    keys, parameter_map = _properties(body, i)
    return _Node(var, tuple(labels), keys, parameter_map)


def _relationship(body: Sequence[_Token]) -> _Relationship:
    i = 0
    var: str | None = None
    if i < len(body) and body[i].kind == "word":
        var = body[i].text
        i += 1
    types: list[str] = []
    while i + 1 < len(body) and body[i].is_symbol(":", "|") and body[i + 1].kind == "word":
        types.append(body[i + 1].text)
        i += 2
    while i < len(body) and (body[i].is_symbol("*", "..") or body[i].kind == "number"):
        i += 1  # a variable-length range
    keys, parameter_map = _properties(body, i)
    return _Relationship(var, tuple(types), bool(keys) or parameter_map)


def _patterns(tokens: Sequence[_Token]) -> list[_Node | _Relationship]:
    """The node and relationship patterns of a MATCH, MERGE or CREATE clause, in order. The
    arguments of a function call (`shortestPath(...)`) are read as patterns too."""
    found: list[_Node | _Relationship] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.is_symbol("("):
            end = _matching(tokens, i)
            body = tokens[i + 1 : end]
            if i > 0 and tokens[i - 1].kind == "word":
                found.extend(_patterns(body))
            else:
                found.append(_node(body))
            i = end + 1
        elif token.is_symbol("["):
            end = _matching(tokens, i)
            found.append(_relationship(tokens[i + 1 : end]))
            i = end + 1
        else:
            i += 1
    return found


class _Check:
    """The state of one statement: the variables its patterns bind and the problems found."""

    def __init__(self) -> None:
        self.problems: list[str] = []
        self.bound: dict[str, str | None] = {}
        self.relationships: set[str] = set()
        self.labels = frozenset(allowlist.ALLOWLIST) | {"ProjectionSource", "ProjectionCursor"}

    def flag(self, problem: str) -> None:
        if problem not in self.problems:
            self.problems.append(problem)

    def permitted(self, label: str) -> frozenset[str]:
        named = {spec.prop for spec in allowlist.ALLOWLIST.get(label, ())}
        return frozenset(named) | allowlist.SYSTEM_PROPERTIES.get(label, frozenset())

    def bind(self, var: str | None, label: str | None) -> None:
        if var is not None and self.bound.get(var) is None:
            self.bound[var] = label

    # --- patterns

    def read_patterns(self, tokens: Sequence[_Token]) -> None:
        for pattern in _patterns(tokens):
            if isinstance(pattern, _Node):
                self.bind(pattern.var, pattern.labels[0] if pattern.labels else None)
            elif pattern.var is not None:
                self.relationships.add(pattern.var)
                self.bound.setdefault(pattern.var, None)

    def write_patterns(self, tokens: Sequence[_Token]) -> None:
        for pattern in _patterns(tokens):
            if isinstance(pattern, _Node):
                self.write_node(pattern)
            else:
                self.write_relationship(pattern)

    def write_node(self, node: _Node) -> None:
        if node.parameter_map:
            self.flag("pattern-parameter-map")
        if len(node.labels) > 1:
            self.flag("multiple-labels")
        for label in node.labels:
            if label not in self.labels:
                self.flag(f"label-not-allowed:{label}")
        if not node.labels:
            if node.var is None:
                self.flag("unlabelled-node")
            elif node.var not in self.bound:
                self.flag("unknown-variable")
            return
        label = node.labels[0]
        if label in self.labels:
            for key in node.keys:
                if key not in self.permitted(label):
                    self.flag(f"property-not-allowed:{label}.{key}")
        self.bind(node.var, label)

    def write_relationship(self, relationship: _Relationship) -> None:
        if relationship.has_properties:
            self.flag("relationship-properties")
        for relationship_type in relationship.types:
            if relationship_type not in allowlist.NETWORK_RELATIONSHIPS:
                self.flag(f"relationship-not-allowed:{relationship_type}")
        if relationship.var is not None:
            self.relationships.add(relationship.var)
            self.bound.setdefault(relationship.var, None)

    # --- other clauses

    def bind_unwind(self, tokens: Sequence[_Token]) -> None:
        if len(tokens) < 3 or tokens[-2].upper != "AS" or tokens[-1].kind != "word":  # noqa: PLR2004
            raise _Unparseable
        self.bound.setdefault(tokens[-1].text, None)

    def bind_with(self, tokens: Sequence[_Token]) -> None:
        for item in _split_commas(tokens):
            if len(item) >= 2 and item[-2].upper == "AS" and item[-1].kind == "word":  # noqa: PLR2004
                source = item[0].text if len(item) == 3 and item[0].kind == "word" else None  # noqa: PLR2004
                self.bound.setdefault(item[-1].text, self.bound.get(source) if source else None)

    def target(self, var: str) -> str | None:
        """Check a variable that a SET changes. Returns its label when it can be checked."""
        if var not in self.bound:
            self.flag("unknown-variable")
            return None
        if var in self.relationships:
            self.flag("relationship-properties")
            return None
        label = self.bound[var]
        if label is None:
            self.flag("unlabelled-variable")
            return None
        if label not in self.labels:
            self.flag(f"label-not-allowed:{label}")
            return None
        return label

    def set_item(self, item: Sequence[_Token]) -> None:
        if len(item) < 3 or item[0].kind != "word":  # noqa: PLR2004
            raise _Unparseable
        var, second = item[0].text, item[1]
        if second.is_symbol("."):
            if (
                item[2].kind not in {"word", "quoted"}
                or len(item) < 5
                or not item[3].is_symbol("=")
            ):  # noqa: PLR2004
                raise _Unparseable
            label = self.target(var)
            if label is not None and item[2].text not in self.permitted(label):
                self.flag(f"property-not-allowed:{label}.{item[2].text}")
        elif second.is_symbol("=", "+="):
            self.target(var)
            self.flag("map-assignment")
        elif second.is_symbol(":"):
            self.target(var)
            self.flag("label-assignment")
        elif second.is_symbol("["):
            self.target(var)
            self.flag("dynamic-property")
        else:
            raise _Unparseable

    def clause(self, clause: _Clause) -> None:
        name = clause.name
        if name == "MATCH":
            self.read_patterns(clause.tokens)
        elif name in {"MERGE", "CREATE"}:
            self.write_patterns(clause.tokens)
        elif name == "UNWIND":
            self.bind_unwind(clause.tokens)
        elif name == "WITH":
            self.bind_with(clause.tokens)
        elif name == "SET":
            for item in _split_commas(clause.tokens):
                self.set_item(item)
        elif name in {"DELETE", "REMOVE"}:
            self.flag("delete-not-allowed")

    def scan(self, tokens: Sequence[_Token]) -> None:
        for i, token in enumerate(tokens):
            if token.kind != "word":
                continue
            if token.text.lower() == "apoc" or token.upper == "CALL":
                self.flag("call-not-allowed")
            following_paren = i + 1 < len(tokens) and tokens[i + 1].is_symbol("(")
            if token.text.lower() in {"keys", "properties"} and following_paren:
                self.flag("dynamic-property")
            if token.upper == "FOREACH":
                self.flag("dynamic-property")


def check_network_write_statement(cypher: str) -> list[str]:
    """The problems of a Cypher statement that writes the network scope, as codes; empty means
    safe. It is a conservative tokenising parse, not a pattern over the whole text: comments are
    removed and string literals masked first, and a statement it cannot read is `unparseable`
    (fail closed). A statement with no write clause has no problems.

    Codes: map-assignment, pattern-parameter-map, relationship-properties,
    property-not-allowed:<Label>.<prop>, label-not-allowed:<Label>, label-assignment,
    multiple-labels, unlabelled-node, unlabelled-variable, dynamic-property, call-not-allowed,
    delete-not-allowed, relationship-not-allowed:<TYPE>, unknown-variable and unparseable."""
    if type(cypher) is not str:
        return [UNPARSEABLE]
    try:
        tokens, backticks = _lex(cypher)
        if not tokens:
            raise _Unparseable
        _check_shape(tokens)
        clauses = _clauses(tokens)
        if not any(clause.name in _WRITE_CLAUSES for clause in clauses):
            return []
        check = _Check()
        if backticks:
            check.flag("dynamic-property")
        check.scan(tokens)
        for clause in clauses:
            check.clause(clause)
    except _Unparseable:
        return [UNPARSEABLE]
    return check.problems


def assert_network_write_statement(cypher: str) -> None:
    """Raise `ValidationFailed` naming the problem codes, never the statement."""
    problems = check_network_write_statement(cypher)
    if problems:
        raise ValidationFailed("statement", "refused: " + ", ".join(problems))
