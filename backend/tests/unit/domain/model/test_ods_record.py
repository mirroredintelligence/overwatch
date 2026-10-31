"""The ODS record an NHS tenant is created from (DEC-1314): what is refused before any write."""

import pytest

from overwatch.domain.errors import ValidationFailed
from overwatch.domain.model.ods_record import (
    MAX_LINKS,
    MAX_ROLES,
    OdsLink,
    OdsOrganisationRecord,
    OdsRole,
)

PRIMARY = OdsRole("RO177", "PRESCRIBING COST CENTRE", True)
SECONDARY = OdsRole("RO76", "GP PRACTICE", False)


def _record(**fields: object) -> OdsOrganisationRecord:
    base: dict[str, object] = {
        "code": "F81044",
        "name": "THE ARDLEIGH SURGERY",
        "status": "Active",
        "postcode": "CO7 7LD",
        "primary_role": "RO177",
        "roles": (PRIMARY, SECONDARY),
        "links": (OdsLink("RE4", "F81045", "A PARENT", "RO98"),),
        "last_changed_at": "2024-05-01",
    }
    return OdsOrganisationRecord(**{**base, **fields})  # type: ignore[arg-type]


def test_a_record_as_the_form_reads_it_is_accepted() -> None:
    record = _record()

    assert record.code == "F81044" and record.primary_role == "RO177"


@pytest.mark.parametrize("code", ["", "f81044", "AB", "TOOLONGCODE", "F8 044", "F81044\n"])
def test_a_code_that_is_not_an_ods_code_is_refused(code: str) -> None:
    with pytest.raises(ValidationFailed) as refused:
        _record(code=code)

    assert refused.value.field == "odsRecord.code"


@pytest.mark.parametrize(
    "fields",
    [
        {"name": ""},
        {"name": "x" * 121},
        {"status": ""},
        {"postcode": ""},
        {"postcode": "X" * 17},
        {"last_changed_at": "d" * 41},
    ],
)
def test_text_that_is_empty_or_too_long_is_refused(fields: dict[str, object]) -> None:
    with pytest.raises(ValidationFailed):
        _record(**fields)


def test_more_roles_or_links_than_the_bounds_are_refused() -> None:
    roles = tuple(OdsRole(f"RO{i}", f"ROLE {i}", False) for i in range(MAX_ROLES + 1))
    links = tuple(OdsLink("RE4", "F81045", "A PARENT", "RO98") for _ in range(MAX_LINKS + 1))

    with pytest.raises(ValidationFailed) as too_many_roles:
        _record(primary_role=None, roles=roles, links=())
    with pytest.raises(ValidationFailed) as too_many_links:
        _record(links=links)

    assert too_many_roles.value.field == "odsRecord.roles"
    assert too_many_links.value.field == "odsRecord.links"


def test_the_primary_role_must_be_the_one_role_flagged_primary() -> None:
    with pytest.raises(ValidationFailed) as not_named:
        _record(primary_role=None)
    with pytest.raises(ValidationFailed) as other:
        _record(primary_role="RO76")

    assert not_named.value.field == "odsRecord.primaryRole"
    assert other.value.field == "odsRecord.primaryRole"


def test_a_record_with_no_primary_role_has_no_flagged_role() -> None:
    record = _record(primary_role=None, roles=(SECONDARY,))

    assert record.primary_role is None


def test_a_role_id_that_is_not_an_ods_role_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        OdsRole("ro 76", "GP PRACTICE", False)


def test_a_link_with_an_empty_role_is_accepted_and_one_with_a_bad_role_is_not() -> None:
    assert OdsLink("RE4", "F81045", "A PARENT", "").role == ""
    with pytest.raises(ValidationFailed):
        OdsLink("RE4", "F81045", "A PARENT", "ro98!")


def test_a_link_needs_an_ods_relationship_id() -> None:
    with pytest.raises(ValidationFailed):
        OdsLink("", "F81045", "A PARENT", "RO98")
    with pytest.raises(ValidationFailed):
        OdsLink("re4!", "F81045", "A PARENT", "RO98")


def test_the_same_role_twice_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        _record(roles=(PRIMARY, OdsRole("RO177", "AGAIN", False)))
