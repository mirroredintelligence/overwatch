"""Command replay: the first result of each command key is kept and returned on a replay (P15).

encode_result turns a command result into (resultType, json text). decode_result is its inverse.
The JSON text is an intermediate form only: the Neo4j store writes it as typed graph nodes and never
stores the text (DEC-001, DEC-090).

Allowed result types are dataclasses and enum members defined in diucs.application or diucs.domain
(DEC-090 item 2). Decoding imports nothing else. Tuples, frozensets, enums, dataclasses, UTC
datetimes and calendar dates keep their types through the round trip, so a replay returns an equal
object.
"""

import dataclasses
import importlib
import json
import math
import re
from datetime import UTC, date, datetime
from enum import Enum
from typing import Protocol

ALLOWED_PACKAGES = ("diucs.application", "diucs.domain")

DATETIME_TAG = "$datetime"
DATE_TAG = "$date"
ENUM_TAG = "$enum"
TUPLE_TAG = "$tuple"
FROZENSET_TAG = "$frozenset"
DATACLASS_TAG = "$type"
FIELDS_KEY = "fields"
VALUE_KEY = "value"

_INSTANT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{6})?Z")
_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_INT_MIN = -(2**63)
_INT_MAX = 2**63 - 1


class IdempotencyStore(Protocol):
    """Replay of a command's first result, per key. A key belongs to the tenant bound to the unit of
    work (TEN-016): the same key in another tenant is a different command, and reads as absent
    there, never as a Conflict. The command fingerprint is the use case's own (it says what the
    command was), not the store's."""

    async def get(self, key: str) -> object | None: ...

    async def put(self, key: str, result: object) -> None: ...


def format_instant(value: datetime) -> str:
    """The canonical text of an aware instant: UTC, to the microsecond when not whole seconds,
    with a Z suffix. parse_instant reads exactly this form back."""
    if value.utcoffset() is None:
        raise ValueError("a stored instant must be timezone-aware")
    utc = value.astimezone(UTC)
    text = utc.strftime("%Y-%m-%dT%H:%M:%S")
    if utc.microsecond:
        text += f".{utc.microsecond:06d}"
    return text + "Z"


def parse_instant(text: str) -> datetime:
    """The aware UTC instant for a canonical text. Any other text is refused."""
    if not _INSTANT.fullmatch(text):
        raise ValueError("an instant must be UTC text in the form 2026-10-23T13:00:00Z")
    value = datetime.fromisoformat(text)
    if format_instant(value) != text:
        raise ValueError("an instant must be UTC text in the form 2026-10-23T13:00:00Z")
    return value


def parse_day(text: str) -> date:
    """The calendar date for a canonical text (YYYY-MM-DD). Any other text is refused."""
    if not _DAY.fullmatch(text):
        raise ValueError("a day must be text in the form 2026-10-23")
    value = date.fromisoformat(text)
    if value.isoformat() != text:
        raise ValueError("a day must be text in the form 2026-10-23")
    return value


def encode_result(result: object) -> tuple[str, str]:
    """(resultType, json text) for a command result. Refuses what decode_result could not return."""
    is_instance = dataclasses.is_dataclass(result) and not isinstance(result, type)
    if not is_instance and not isinstance(result, Enum):
        raise ValueError("a command result must be a dataclass or an enum member")
    cls = type(result)
    _check_type(cls)
    return _type_name(cls), _canonical(_encode(result))


def decode_result(type_name: str, json_text: str) -> object:
    """The result a stored (resultType, json text) pair stands for. Raises ValueError for a type
    outside the allowed packages, or for text that does not match the type."""
    cls = _resolve(type_name)
    if not (dataclasses.is_dataclass(cls) or issubclass(cls, Enum)):
        raise ValueError(f"result type {type_name!r} is not a dataclass or an enum")
    value = _decode(json.loads(json_text))
    if not isinstance(value, cls):
        raise ValueError(f"stored result does not match its type {type_name!r}")
    return value


def _canonical(tree: object) -> str:
    return json.dumps(tree, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _type_name(cls: type) -> str:
    return f"{cls.__module__}:{cls.__qualname__}"


def _check_type(cls: type) -> None:
    module = cls.__module__
    if not any(module == pkg or module.startswith(pkg + ".") for pkg in ALLOWED_PACKAGES):
        raise ValueError(f"result type {_type_name(cls)!r} is outside the allowed packages")
    if "<" in cls.__qualname__:
        raise ValueError(f"result type {_type_name(cls)!r} is local and cannot be decoded")


def _encode(value: object) -> object:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, Enum):
        _check_type(type(value))
        return {ENUM_TAG: _type_name(type(value)), VALUE_KEY: _encode(value.value)}
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        if not _INT_MIN <= value <= _INT_MAX:
            raise ValueError("an integer result must fit in 64 bits")
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("a non-finite number cannot be stored")
        return value
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise ValueError("a naive datetime cannot be stored")
        return {DATETIME_TAG: format_instant(value)}
    if isinstance(value, date):
        return {DATE_TAG: value.isoformat()}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        cls = type(value)
        _check_type(cls)
        fields: dict[str, object] = {}
        for field in dataclasses.fields(value):
            if not field.init:
                raise ValueError(f"field {field.name!r} is not an init field and cannot be decoded")
            fields[field.name] = _encode(getattr(value, field.name))
        return {DATACLASS_TAG: _type_name(cls), FIELDS_KEY: fields}
    if isinstance(value, tuple):
        return {TUPLE_TAG: [_encode(item) for item in value]}
    if isinstance(value, frozenset):
        items = [_encode(item) for item in value]
        items.sort(key=_canonical)
        return {FROZENSET_TAG: items}
    if isinstance(value, list):
        return [_encode(item) for item in value]
    raise ValueError(f"a {type(value).__name__} cannot be stored in a command result")


def _resolve(type_name: str) -> type:
    module_name, separator, qualname = type_name.partition(":")
    if not separator or not qualname:
        raise ValueError(f"result type {type_name!r} is not module:qualname")
    if not any(module_name == pkg or module_name.startswith(pkg + ".") for pkg in ALLOWED_PACKAGES):
        raise ValueError(f"result type {type_name!r} is outside the allowed packages")
    try:
        target: object = importlib.import_module(module_name)
    except ImportError as error:
        raise ValueError(f"result type {type_name!r} cannot be imported") from error
    for part in qualname.split("."):
        target = getattr(target, part, None)
        if target is None:
            raise ValueError(f"result type {type_name!r} does not exist")
    if not isinstance(target, type):
        raise ValueError(f"result type {type_name!r} is not a type")
    return target


def _decode(tree: object) -> object:
    if tree is None or isinstance(tree, (bool, int, float, str)):
        return tree
    if isinstance(tree, list):
        return [_decode(item) for item in tree]
    if not isinstance(tree, dict):
        raise ValueError("unrecognised stored value")
    keys = set(tree)
    if keys == {DATETIME_TAG}:
        return parse_instant(_text(tree[DATETIME_TAG]))
    if keys == {DATE_TAG}:
        return parse_day(_text(tree[DATE_TAG]))
    if keys == {ENUM_TAG, VALUE_KEY}:
        enum_cls = _resolve(_text(tree[ENUM_TAG]))
        if not issubclass(enum_cls, Enum):
            raise ValueError("stored enum names a type that is not an enum")
        return enum_cls(_decode(tree[VALUE_KEY]))
    if keys == {TUPLE_TAG}:
        return tuple(_decode(item) for item in _items(tree[TUPLE_TAG]))
    if keys == {FROZENSET_TAG}:
        return frozenset(_decode(item) for item in _items(tree[FROZENSET_TAG]))
    if keys == {DATACLASS_TAG, FIELDS_KEY}:
        cls = _resolve(_text(tree[DATACLASS_TAG]))
        if not dataclasses.is_dataclass(cls):
            raise ValueError("stored dataclass names a type that is not a dataclass")
        fields = tree[FIELDS_KEY]
        if not isinstance(fields, dict):
            raise ValueError("stored dataclass fields must be an object")
        try:
            return cls(**{name: _decode(value) for name, value in fields.items()})
        except TypeError as error:
            raise ValueError("stored dataclass fields do not match its type") from error
    raise ValueError("unrecognised stored value")


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("a stored name must be text")
    return value


def _items(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("a stored collection must be a list")
    return value
