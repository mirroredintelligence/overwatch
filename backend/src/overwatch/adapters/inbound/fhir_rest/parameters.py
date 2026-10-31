"""Readers for the FHIR Parameters bodies of the operation routes (R10, reused by R12 and R13).

A body is read into an index by part name. A part with one typed value is read with `single`, a
part that repeats with `repeated`. Every refusal names the part, never its value, so no error
body can carry a name, a number or free text from the request (DEC-086 items 2 to 5).
"""

from enum import StrEnum
from typing import Any, Final

from diucs.domain.errors import ValidationFailed

PARAMETERS: Final = "Parameters"
VALUE_KEYS: Final = (
    "valueString",
    "valueCode",
    "valueInteger",
    "valueBoolean",
    "valueDate",
    "valueDateTime",
    "valueReference",
)

Index = dict[str, list[dict[str, Any]]]


def index_parameters(body: object) -> Index:
    """The parts of a Parameters body by name. The body must be a Parameters resource; a part with
    no name is refused."""
    if not isinstance(body, dict) or body.get("resourceType") != PARAMETERS:
        raise ValidationFailed(PARAMETERS, "the body must be a FHIR Parameters resource")
    index: Index = {}
    for item in body.get("parameter") or []:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise ValidationFailed("parameter", "every parameter needs a name")
        index.setdefault(item["name"], []).append(item)
    return index


def _value_of(item: dict[str, Any], name: str) -> object:
    for key in VALUE_KEYS:
        if key in item:
            return item[key]
    raise ValidationFailed(name, "has no value")


def single(index: Index, name: str, *, required: bool) -> object | None:
    """The one value of a part, or None when it is optional and absent. Given twice is refused."""
    items = index.get(name, [])
    if not items:
        if required:
            raise ValidationFailed(name, "is required")
        return None
    if len(items) > 1:
        raise ValidationFailed(name, "is given once")
    return _value_of(items[0], name)


def repeated(index: Index, name: str) -> list[object]:
    """Every value of a part that may repeat, in order."""
    return [_value_of(item, name) for item in index.get(name, [])]


def text(value: object, name: str, *, limit: int | None = None) -> str:
    """A string value, not blank, at most `limit` characters when one is given."""
    if not isinstance(value, str) or not value.strip():
        raise ValidationFailed(name, "is required")
    if limit is not None and len(value) > limit:
        raise ValidationFailed(name, f"must be at most {limit} characters")
    return value


def optional_text(value: object | None, name: str, *, limit: int | None = None) -> str:
    """A string value that may be absent (then the empty string)."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValidationFailed(name, "must be text")
    if limit is not None and len(value) > limit:
        raise ValidationFailed(name, f"must be at most {limit} characters")
    return value


def enum_value[E: StrEnum](enum_cls: type[E], value: object, name: str) -> E:
    """The enum member a code names. Anything else is refused with the part's name."""
    try:
        return enum_cls(str(value))
    except ValueError:
        raise ValidationFailed(name, f"is not a known {name}") from None


def whole(value: object, name: str) -> int:
    """A whole number (a boolean is not one)."""
    if type(value) is not int:
        raise ValidationFailed(name, "must be a whole number")
    return value


def reference_id(value: object, name: str, resource_type: str) -> str:
    """The id a reference names: `<id>` or `<ResourceType>/<id>`. Another type is refused."""
    if not isinstance(value, str) or not value:
        raise ValidationFailed(name, "is required")
    prefix = f"{resource_type}/"
    if value.startswith(prefix):
        value = value[len(prefix) :]
    if not value or "/" in value:
        raise ValidationFailed(name, f"must name a {resource_type}")
    return value


def reference_part(item: dict[str, Any], name: str, resource_type: str) -> str:
    """The id of a part given as a valueString id or as a valueReference of one resource type."""
    if "valueReference" in item and isinstance(item["valueReference"], dict):
        return reference_id(item["valueReference"].get("reference"), name, resource_type)
    return reference_id(_value_of(item, name), name, resource_type)


__all__ = [
    "PARAMETERS",
    "Index",
    "enum_value",
    "index_parameters",
    "optional_text",
    "reference_id",
    "reference_part",
    "repeated",
    "single",
    "text",
    "whole",
]
