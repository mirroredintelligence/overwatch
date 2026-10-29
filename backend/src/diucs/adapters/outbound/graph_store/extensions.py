"""Extension registry (R8): an extension URL maps to a short name and a value type.

A registered extension is stored as the property `ext_<shortName>`. The mapper refuses any URL
that is not registered (UnknownExtension); nothing is dropped. Registration is one call:
`register_extension(ExtensionDef(...))`. A short name the tenancy seam owns is refused
(`TENANT_OWNED_NAMES`), so no extension can stand in for the tenant stamp.
"""

import re
from dataclasses import dataclass
from typing import Final, Literal

from diucs.domain.codes import BASE_URL

ValueType = Literal["string", "integer", "boolean", "dateTime", "decimal"]

_SHORT_NAME: Final = re.compile(r"[A-Za-z][A-Za-z0-9]*")
VALUE_KEYS: Final[dict[ValueType, str]] = {
    "string": "valueString",
    "integer": "valueInteger",
    "boolean": "valueBoolean",
    "dateTime": "valueDateTime",
    "decimal": "valueDecimal",
}
PROPERTY_PREFIX: Final = "ext_"
# Names the tenancy seam owns (DEC-162). `tenantId` is stamped on every node by the writer from the
# bound scope (DEC-130) and `sourceTenantId` marks a network projection (DEC-132). A resource can
# carry neither, so the mapper refuses an element of that name and this registry refuses an
# extension whose short name is one.
TENANT_OWNED_NAMES: Final[frozenset[str]] = frozenset({"tenantId", "sourceTenantId"})


@dataclass(frozen=True, slots=True)
class ExtensionDef:
    url: str
    short_name: str
    value_type: ValueType

    def __post_init__(self) -> None:
        if self.short_name in TENANT_OWNED_NAMES:
            raise ValueError("short name is reserved for the tenancy seam")
        # No underscore: the property name ext_<shortName> must split unambiguously on the prefix.
        if not _SHORT_NAME.fullmatch(self.short_name):
            raise ValueError("short name must be letters and digits, starting with a letter")
        if self.url != f"{BASE_URL}StructureDefinition/{self.short_name}":
            raise ValueError("url must be the StructureDefinition URL for the short name")

    @property
    def property_name(self) -> str:
        return f"{PROPERTY_PREFIX}{self.short_name}"

    @property
    def value_key(self) -> str:
        return VALUE_KEYS[self.value_type]


EXTENSIONS: dict[str, ExtensionDef] = {}


def register_extension(defn: ExtensionDef) -> None:
    if defn.url in EXTENSIONS:
        raise ValueError(f"extension already registered: {defn.short_name}")
    EXTENSIONS[defn.url] = defn


def by_short_name(short_name: str) -> ExtensionDef | None:
    return next((defn for defn in EXTENSIONS.values() if defn.short_name == short_name), None)


register_extension(
    ExtensionDef(f"{BASE_URL}StructureDefinition/smsShortName", "smsShortName", "string")
)
register_extension(
    ExtensionDef(
        f"{BASE_URL}StructureDefinition/establishedCapacity", "establishedCapacity", "integer"
    )
)
register_extension(
    ExtensionDef(
        f"{BASE_URL}StructureDefinition/canExceedEstablished", "canExceedEstablished", "boolean"
    )
)
register_extension(
    ExtensionDef(f"{BASE_URL}StructureDefinition/usualRangeMin", "usualRangeMin", "integer")
)
register_extension(
    ExtensionDef(f"{BASE_URL}StructureDefinition/usualRangeMax", "usualRangeMax", "integer")
)
register_extension(
    ExtensionDef(f"{BASE_URL}StructureDefinition/reportCadence", "reportCadence", "string")
)
register_extension(
    ExtensionDef(
        f"{BASE_URL}StructureDefinition/limitedLevelPercent", "limitedLevelPercent", "integer"
    )
)
register_extension(
    ExtensionDef(f"{BASE_URL}StructureDefinition/geocodeSource", "geocodeSource", "string")
)
register_extension(
    ExtensionDef(f"{BASE_URL}StructureDefinition/geocodedAt", "geocodedAt", "dateTime")
)
register_extension(ExtensionDef(f"{BASE_URL}StructureDefinition/uprn", "uprn", "string"))
register_extension(
    ExtensionDef(f"{BASE_URL}StructureDefinition/reportType", "reportType", "string")
)
register_extension(
    ExtensionDef(f"{BASE_URL}StructureDefinition/referrerType", "referrerType", "string")
)
# P01: a service's measure, unit label and channel (service profile, domain-rules 1.1).
register_extension(ExtensionDef(f"{BASE_URL}StructureDefinition/measure", "measure", "string"))
register_extension(ExtensionDef(f"{BASE_URL}StructureDefinition/unitLabel", "unitLabel", "string"))
register_extension(ExtensionDef(f"{BASE_URL}StructureDefinition/channel", "channel", "string"))
# P03: a post's cover (domain-rules 2.4). The cover practitioner and the time the cover ends.
register_extension(ExtensionDef(f"{BASE_URL}StructureDefinition/coveredBy", "coveredBy", "string"))
register_extension(
    ExtensionDef(f"{BASE_URL}StructureDefinition/coveredUntil", "coveredUntil", "dateTime")
)
# P21: a case's age band (on the Patient stub), urgency, close time, outcome and the reason the
# best fit was not used (on the ServiceRequest). Domain values are stored as their codes.
register_extension(ExtensionDef(f"{BASE_URL}StructureDefinition/ageBand", "ageBand", "string"))
register_extension(ExtensionDef(f"{BASE_URL}StructureDefinition/urgency", "urgency", "string"))
register_extension(ExtensionDef(f"{BASE_URL}StructureDefinition/closedAt", "closedAt", "dateTime"))
register_extension(ExtensionDef(f"{BASE_URL}StructureDefinition/outcome", "outcome", "string"))
register_extension(
    ExtensionDef(f"{BASE_URL}StructureDefinition/bestFitNotUsed", "bestFitNotUsed", "string")
)
# P13: a registration's four approval checks (domain-rules 6.2). checkScope holds the scope flag
# and is left out until the scope is decided.
register_extension(
    ExtensionDef(f"{BASE_URL}StructureDefinition/checkAutomatic", "checkAutomatic", "boolean")
)
register_extension(
    ExtensionDef(f"{BASE_URL}StructureDefinition/checkCallback", "checkCallback", "boolean")
)
register_extension(
    ExtensionDef(f"{BASE_URL}StructureDefinition/checkScope", "checkScope", "string")
)
register_extension(
    ExtensionDef(f"{BASE_URL}StructureDefinition/checkCriteria", "checkCriteria", "boolean")
)
