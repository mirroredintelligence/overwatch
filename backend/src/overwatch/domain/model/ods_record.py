"""The NHS Organisation Data Service (ODS) record an NHS tenant is created from (DEC-1313/1314).

The record is what the operator confirmed on the create form: the organisation's code, name, status
and postcode, its roles (one primary), and its active links. It is checked here, before any write,
and is immutable. It holds no patient data and no personal data: it describes an organisation.
"""

import re
from dataclasses import dataclass
from typing import Final

from overwatch.domain.errors import ValidationFailed

ODS_CODE: Final = re.compile(r"[A-Z0-9]{3,8}")
ODS_ROLE: Final = re.compile(r"[A-Z0-9]{1,20}")
ODS_RELATIONSHIP: Final = re.compile(r"[A-Z0-9]{1,10}")
MAX_ROLES: Final = 20
MAX_LINKS: Final = 50
MAX_NAME: Final = 120
MAX_STATUS: Final = 40
MAX_POSTCODE: Final = 16
MAX_DATE: Final = 40


def _text(field: str, value: object, max_length: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise ValidationFailed(field, f"must be text of 1 to {max_length} characters")
    return value


def _optional_text(field: str, value: object, max_length: int) -> str | None:
    if value is None:
        return None
    return _text(field, value, max_length)


@dataclass(frozen=True, slots=True)
class OdsRole:
    id: str
    name: str
    primary: bool

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or ODS_ROLE.fullmatch(self.id) is None:
            raise ValidationFailed("role", "must be an ODS role id")
        _text("role.name", self.name, MAX_NAME)
        if not isinstance(self.primary, bool):
            raise ValidationFailed("role.primary", "must be true or false")


@dataclass(frozen=True, slots=True)
class OdsLink:
    """An active relationship of the record: its ODS relationship id (for example RE4), the linked
    organisation's code, its name, and its primary role id ('' when it has none). The relationship
    id keeps the meaning (commissioned by, member of, and so on); a FHIR `partOf` would not."""

    relationship: str
    code: str
    name: str
    role: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.relationship, str)
            or ODS_RELATIONSHIP.fullmatch(self.relationship) is None
        ):
            raise ValidationFailed("link.relationship", "must be an ODS relationship id")
        if not isinstance(self.code, str) or ODS_CODE.fullmatch(self.code) is None:
            raise ValidationFailed("link.code", "must be an ODS code")
        _text("link.name", self.name, MAX_NAME)
        if not isinstance(self.role, str) or (
            self.role != "" and ODS_ROLE.fullmatch(self.role) is None
        ):
            raise ValidationFailed("link.role", "must be an ODS role id or empty")


@dataclass(frozen=True, slots=True)
class OdsOrganisationRecord:
    code: str
    name: str
    status: str
    postcode: str | None
    primary_role: str | None
    roles: tuple[OdsRole, ...]
    links: tuple[OdsLink, ...]
    last_changed_at: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or ODS_CODE.fullmatch(self.code) is None:
            raise ValidationFailed("odsRecord.code", "must be an ODS code")
        _text("odsRecord.name", self.name, MAX_NAME)
        _text("odsRecord.status", self.status, MAX_STATUS)
        _optional_text("odsRecord.postcode", self.postcode, MAX_POSTCODE)
        _optional_text("odsRecord.lastChangedAt", self.last_changed_at, MAX_DATE)
        if self.primary_role is not None and (
            not isinstance(self.primary_role, str) or ODS_ROLE.fullmatch(self.primary_role) is None
        ):
            raise ValidationFailed("odsRecord.primaryRole", "must be an ODS role id")
        if len(self.roles) > MAX_ROLES:
            raise ValidationFailed("odsRecord.roles", f"at most {MAX_ROLES} roles")
        if len(self.links) > MAX_LINKS:
            raise ValidationFailed("odsRecord.links", f"at most {MAX_LINKS} links")
        if not all(isinstance(role, OdsRole) for role in self.roles):
            raise ValidationFailed("odsRecord.roles", "must be roles")
        if not all(isinstance(link, OdsLink) for link in self.links):
            raise ValidationFailed("odsRecord.links", "must be links")
        if len({role.id for role in self.roles}) != len(self.roles):
            raise ValidationFailed("odsRecord.roles", "a role appears twice")
        primaries = [role.id for role in self.roles if role.primary]
        if self.primary_role is None:
            if primaries:
                raise ValidationFailed(
                    "odsRecord.primaryRole", "a primary role is flagged but not named"
                )
        elif primaries != [self.primary_role]:
            raise ValidationFailed("odsRecord.primaryRole", "must be the one role flagged primary")
