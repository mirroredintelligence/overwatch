"""The tenant's own copy of its NHS organisation, as a FHIR transaction bundle (DEC-1313, DEC-1314).

`CreateTenant` writes this bundle into the new tenant's scope, once, through the same path the
registration uses for its organisation (`uow.registrations.write_bundle`). Nothing here is shared:
the bundle names no other tenant and no global node.

The mapping is in DEC-1314 item 3. The mapper refuses an element it does not represent, so every
field below is one the mapper maps (`ext_*` properties for the three registered extensions,
the `Organization_Link` backbone for links).
"""

from datetime import UTC, datetime
from typing import Any, Final

from overwatch.application.use_cases.registration_submit import ODS_ORG_SYSTEM
from overwatch.domain.codes import BASE_URL, code_system_url
from overwatch.domain.model.ods_record import OdsOrganisationRecord

ODS_ROLE_SYSTEM: Final = code_system_url("ods-organisation-role")
"""An overwatch CodeSystem for ODS role ids. The NHS URI for these is unverified (DEC-1314)."""
COUNTRY: Final = "GB"
ACTIVE: Final = "Active"
EXT_PRIMARY_ROLE: Final = "odsPrimaryRole"
EXT_SNAPSHOT_AT: Final = "odsSnapshotAt"
EXT_LAST_CHANGED_AT: Final = "odsLastChangedAt"


def _extension(short_name: str, key: str, value: str) -> dict[str, str]:
    return {"url": f"{BASE_URL}StructureDefinition/{short_name}", key: value}


def _stamp(now: datetime) -> str:
    return now.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def organisation_resource(
    *, ods_code: str, legal_name: str, record: OdsOrganisationRecord | None, now: datetime
) -> dict[str, Any]:
    """The Organization for an NHS tenant. Without a record (an organisation entered by hand) it
    carries the code and the legal name only: nothing is claimed that was not read from ODS."""
    resource: dict[str, Any] = {
        "resourceType": "Organization",
        "id": ods_code,
        "identifier": [{"system": ODS_ORG_SYSTEM, "value": ods_code}],
        "name": legal_name,
    }
    if record is None:
        return resource
    resource["name"] = record.name
    resource["active"] = record.status == ACTIVE
    if record.postcode is not None:
        resource["address"] = [{"postalCode": record.postcode, "country": COUNTRY}]
    resource["type"] = [
        {"coding": [{"system": ODS_ROLE_SYSTEM, "code": role.id, "display": role.name}]}
        for role in record.roles
    ]
    extensions = [_extension(EXT_SNAPSHOT_AT, "valueDateTime", _stamp(now))]
    if record.primary_role is not None:
        extensions.append(_extension(EXT_PRIMARY_ROLE, "valueString", record.primary_role))
    if record.last_changed_at is not None:
        extensions.append(_extension(EXT_LAST_CHANGED_AT, "valueString", record.last_changed_at))
    resource["extension"] = extensions
    if record.links:
        resource["link"] = [
            {"code": link.code, "display": link.name, "role": link.role} for link in record.links
        ]
    return resource


def organisation_bundle(
    *, ods_code: str, legal_name: str, record: OdsOrganisationRecord | None, now: datetime
) -> dict[str, Any]:
    """A transaction bundle with one PUT: the tenant's Organization, replacing any earlier version
    of it (an interrupted creation that runs again writes a new version of the same node)."""
    resource = organisation_resource(
        ods_code=ods_code, legal_name=legal_name, record=record, now=now
    )
    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            {
                "fullUrl": f"urn:uuid:{ods_code}",
                "resource": resource,
                "request": {"method": "PUT", "url": f"Organization/{ods_code}"},
            }
        ],
    }
