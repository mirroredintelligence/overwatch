"""STUB (U27 red): declarations only."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.geo import AddressCandidate, Geocoder
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.terminology import Terminology
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.registration_draft import RegistrationDraft
from diucs.domain.codes import Measure
from diucs.domain.model.registration import Registration

ODS_ORG_SYSTEM: Final = "https://fhir.nhs.uk/Id/ods-organization-code"
UPRN_SYSTEM: Final = "https://diucs.example/uprn"
GEOCODE_SOURCE: Final = "os-places"
LOOKUPS_STEP: Final = "lookups"
UNIT_LABELS: Final[Mapping[Measure, str]] = {}
DISTRICT_TYPE_CODE: Final = "postcode-district"


@dataclass(frozen=True, slots=True)
class Lookups:
    ods_found: bool
    ods_active: bool
    ods_name: str | None
    ods_type: str | None
    address_found: bool
    address_district: str | None
    checked_at: datetime


@dataclass(frozen=True, slots=True)
class PersistRegistrationCommand:
    registration_id: str


@dataclass(frozen=True, slots=True)
class PersistRegistrationResult:
    persisted: bool
    service_id: str


def encode_lookups(lookups: Lookups) -> dict[str, Any]:
    raise NotImplementedError


def decode_lookups(values: Mapping[str, Any]) -> Lookups:
    raise NotImplementedError


def lookups_of(registration: Registration) -> Lookups | None:
    raise NotImplementedError


def choose_address(candidates: Sequence[AddressCandidate], text: str) -> AddressCandidate | None:
    raise NotImplementedError


def unit_label(measure: Measure) -> str:
    raise NotImplementedError


def build_registration_bundle(
    draft: RegistrationDraft,
    ids: IdGenerator,
    now: datetime,
    address: AddressCandidate | None,
    *,
    service_id: str,
    owner_role_id: str,
    existing_districts: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    raise NotImplementedError


class PersistRegistration:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        geocoder: Geocoder,
        terminology: Terminology,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        raise NotImplementedError

    async def execute(self, command: PersistRegistrationCommand) -> PersistRegistrationResult:
        raise NotImplementedError


