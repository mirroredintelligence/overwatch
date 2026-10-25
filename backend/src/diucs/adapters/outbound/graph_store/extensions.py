"""Extension registry (R8): maps an extension URL to a short name and a value type (G04 stub)."""

from dataclasses import dataclass
from typing import Literal

ValueType = Literal["string", "integer", "boolean", "dateTime", "decimal"]


@dataclass(frozen=True, slots=True)
class ExtensionDef:
    url: str
    short_name: str
    value_type: ValueType


EXTENSIONS: dict[str, ExtensionDef] = {}


def register_extension(defn: ExtensionDef) -> None:
    raise NotImplementedError
