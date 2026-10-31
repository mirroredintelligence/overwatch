"""The pure rules of the advisor's work phone (W44, DEC-1034, DEC-1178): who may record it and
which numbers are accepted. The store, the audit and the two tenants are in
tests/integration/application/test_advisor_work_phone.py. Sample numbers only (07700 900xxx)."""

import dataclasses

import pytest

from diucs.application.actor import Actor
from diucs.application.use_cases.advisor_work_phone import (
    ALLOWED_ROLES,
    check_may_record,
    checked_work_phone,
)
from diucs.domain.codes import Role
from diucs.domain.errors import NotAllowed, ValidationFailed
from tests.support.actors import ACTOR_TENANT

ADMIN = Actor(
    role=Role.TENANT_ADMIN,
    practitioner_id="admin-1",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
    tenant_id=ACTOR_TENANT,
)


def test_only_the_tenant_administrator_records_a_work_phone() -> None:
    assert frozenset({Role.TENANT_ADMIN}) == ALLOWED_ROLES
    check_may_record(ADMIN)
    for role in Role:
        if role is not Role.TENANT_ADMIN:
            with pytest.raises(NotAllowed):
                check_may_record(dataclasses.replace(ADMIN, role=role))


@pytest.mark.parametrize(
    "text", ["07700 900123", "07700900123", "+44 7700 900123", " 07700-900123 "]
)
def test_a_full_uk_number_is_accepted_as_given_without_the_spaces_at_the_ends(text: str) -> None:
    assert checked_work_phone(text) == text.strip()


@pytest.mark.parametrize(
    "text", ["", "   ", "0770090012", "077009001234", "+1 202 555 0100", "notanumber"]
)
def test_anything_that_is_not_a_full_uk_number_is_refused_and_never_echoed(text: str) -> None:
    with pytest.raises(ValidationFailed) as refused:
        checked_work_phone(text)

    assert refused.value.field == "phone"
    assert text.strip() == "" or text.strip() not in str(refused.value)
