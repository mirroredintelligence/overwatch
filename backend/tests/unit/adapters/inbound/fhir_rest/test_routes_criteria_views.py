"""The criteria reads the owner's and the approver's pages need (W7B B): the current values with the
draft that was sent back and the change that is waiting, the overdue date and the shift lead to
ask, the pending change in words with its reason, author and whether the reader wrote it, and the
history with the date of each change and the role of its author.

Through the app on recording stand-ins. The owner reads only the criteria of a service they hold
the owner post for (another service, an unknown one and a role the route does not take are the one
404); a clinical lead and the shift lead read any. The shift lead's phone is the tenant's own
contact, never a default. Sample values only."""

import dataclasses
from datetime import date

import pytest

from diucs.domain.codes import CriteriaStatus, NeedCategory, Role
from diucs.domain.model.criteria import ServiceCriteria
from diucs.domain.model.tenant import ContactKind, TenantContact
from tests.support.w7b_rig import (
    CLINICAL,
    OWNER,
    SERVICE,
    SERVICE_NAME,
    Rig,
    bearer,
    client,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")

OWNER_AUTH = bearer(Role.OWNER, OWNER)
CLINICAL_AUTH = bearer(Role.CLINICAL, CLINICAL)
LEAD_AUTH = bearer(Role.LEAD, "prac-lead")
OVERVIEW = f"/criteria/{SERVICE}"
PENDING = f"/criteria/{SERVICE}/pending"
HISTORY = f"/fhir/Basic?subject=HealthcareService/{SERVICE}"


def _world(**kwargs: date) -> Rig:
    rig = Rig()
    rig.criteria_world(**kwargs)
    return rig


def _version(rig: Rig, **changes: object) -> ServiceCriteria:
    base = rig.units.criteria.versions["crit-2"]
    return dataclasses.replace(
        base,
        id="crit-3",
        version=3,
        status=CriteriaStatus.PENDING_APPROVAL,
        age_min=16,
        age_max=90,
        accepts=frozenset({NeedCategory.FRAILTY}),
        excludes=frozenset({NeedCategory.IV_THERAPY, NeedCategory.PALLIATIVE}),
        districts=frozenset({"DT4", "DT5", "DT6"}),
        change_reason="Takes younger adults from DT6 as well.",
        supersedes_id="crit-2",
        review_months=3,
        changed_on=date(2026, 10, 28),
        **changes,  # type: ignore[arg-type]
    )


def _shift_lead(rig: Rig) -> None:
    rig.units.tenant_config.contact_list = (
        TenantContact(ContactKind.SHIFT_LEAD_ESCALATION, "SPOA shift lead", "01305 000999"),
        TenantContact(ContactKind.COORDINATION_PHONE, "Coordination", "01305 000111"),
    )


# -------------------------------------------------------------------------------- the overview


async def test_the_owner_reads_the_current_values_of_their_service() -> None:
    rig = _world()
    async with client(rig) as http:
        response = await http.get(OVERVIEW, headers=OWNER_AUTH)

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["serviceId"], body["serviceName"]) == (SERVICE, SERVICE_NAME)
    assert body["current"] == {
        "id": "crit-2",
        "version": 2,
        "status": "current",
        "reviewBy": "2027-01-15",
        "ageMin": 18,
        "ageMax": None,
        "accepts": [
            {"code": "frailty", "label": "Frailty"},
            {"code": "wound-care", "label": "Wound care"},
        ],
        "excludes": [{"code": "iv-therapy", "label": "IV therapy"}],
        "districts": ["DT4", "DT5"],
        "changedOn": "2026-09-12",
        "authorRole": "Clinical lead, UCR",
    }
    assert body["draft"] is None and body["pending"] is None
    assert body["isOwner"] is True
    assert body["overdue"] is False and body["overdueSince"] is None
    assert body["shiftLead"] is None
    assert response.headers["cache-control"] == "no-store"


async def test_an_overdue_review_gives_the_date_it_was_due_and_the_shift_lead_to_ask() -> None:
    rig = _world(review_by=date(2026, 10, 27))
    _shift_lead(rig)
    async with client(rig) as http:
        body = (await http.get(OVERVIEW, headers=OWNER_AUTH)).json()

    assert body["overdue"] is True
    assert body["overdueSince"] == "2026-10-27"
    assert body["shiftLead"] == {"label": "SPOA shift lead", "phone": "01305 000999"}


async def test_a_review_due_today_is_not_yet_overdue() -> None:
    rig = _world(review_by=date(2026, 10, 30))
    async with client(rig) as http:
        body = (await http.get(OVERVIEW, headers=OWNER_AUTH)).json()
    assert body["overdue"] is False


async def test_the_overview_has_no_shift_lead_when_the_tenant_has_not_given_one() -> None:
    rig = _world(review_by=date(2026, 10, 27))
    rig.units.tenant_config.contact_list = (
        TenantContact(ContactKind.COORDINATION_PHONE, "Coordination", "01305 000111"),
    )
    async with client(rig) as http:
        body = (await http.get(OVERVIEW, headers=OWNER_AUTH)).json()
    assert body["shiftLead"] is None


async def test_the_draft_that_was_sent_back_and_the_change_waiting_are_told_apart() -> None:
    rig = _world()
    returned = dataclasses.replace(_version(rig), status=CriteriaStatus.DRAFT)
    rig.units.criteria.versions["crit-3"] = returned
    async with client(rig) as http:
        sent_back = (await http.get(OVERVIEW, headers=OWNER_AUTH)).json()
    rig.units.criteria.versions["crit-3"] = _version(rig)
    async with client(rig) as http:
        waiting = (await http.get(OVERVIEW, headers=OWNER_AUTH)).json()

    assert sent_back["draft"]["id"] == "crit-3"
    assert sent_back["draft"]["changeReason"] == "Takes younger adults from DT6 as well."
    assert sent_back["draft"]["ageMin"] == 16
    assert sent_back["pending"] is None
    assert waiting["draft"] is None
    assert waiting["pending"] == {
        "id": "crit-3",
        "version": 3,
        "changeReason": "Takes younger adults from DT6 as well.",
        "changedOn": "2026-10-28",
    }


async def test_a_clinical_lead_and_the_shift_lead_read_any_service_and_isowner_is_false() -> None:
    rig = _world()
    async with client(rig) as http:
        clinical = await http.get(OVERVIEW, headers=CLINICAL_AUTH)
        lead = await http.get(OVERVIEW, headers=LEAD_AUTH)

    assert clinical.status_code == lead.status_code == 200
    assert clinical.json()["isOwner"] is False


async def test_another_owner_an_unknown_service_and_other_roles_are_one_404() -> None:
    rig = _world()
    async with client(rig) as http:
        other = await http.get(OVERVIEW, headers=bearer(Role.OWNER, "prac-someone-else"))
        unknown = await http.get("/criteria/svc-nope", headers=CLINICAL_AUTH)
        advisor = await http.get(OVERVIEW, headers=bearer(Role.ADVISOR, "prac-adv"))
        reporter = await http.get(OVERVIEW, headers=bearer(Role.REPORTER, OWNER, (SERVICE,)))

    assert {other.status_code, unknown.status_code, advisor.status_code, reporter.status_code} == {
        404
    }
    assert other.content == unknown.content == advisor.content


# ---------------------------------------------------------------------------- the pending change


async def test_the_pending_change_is_told_in_words_with_its_reason_and_author() -> None:
    rig = _world()
    rig.units.criteria.versions["crit-3"] = _version(rig)
    async with client(rig) as http:
        response = await http.get(PENDING, headers=CLINICAL_AUTH)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["criteriaId"] == "crit-3"
    assert body["version"] == 3
    assert body["changeReason"] == "Takes younger adults from DT6 as well."
    assert body["authorRole"] == "Clinical lead, UCR"
    assert body["isAuthor"] is False
    assert body["reviewMonths"] == 3
    assert body["criteria"]["ageMin"] == 16 and body["criteria"]["ageMax"] == 90
    assert {change["field"]: change["words"] for change in body["changes"]} == {
        "ageMin": "Youngest age: 18 becomes 16",
        "ageMax": "Oldest age: no limit becomes 90",
        "accepts": "No longer accepts: Wound care",
        "excludes": "Now excludes: Palliative",
        "districts": "Now covers: DT6",
    }
    assert [change["label"] for change in body["changes"]] == [
        "Youngest age",
        "Oldest age",
        "Accepts",
        "Excludes",
        "Districts",
    ]


async def test_the_author_is_told_they_wrote_it() -> None:
    rig = _world()
    rig.units.criteria.versions["crit-3"] = _version(rig)
    async with client(rig) as http:
        mine = (await http.get(PENDING, headers=OWNER_AUTH)).json()
        theirs = (await http.get(PENDING, headers=CLINICAL_AUTH)).json()
    assert mine["isAuthor"] is True
    assert theirs["isAuthor"] is False


async def test_a_change_that_changes_nothing_has_no_words() -> None:
    rig = _world()
    base = rig.units.criteria.versions["crit-2"]
    rig.units.criteria.versions["crit-3"] = dataclasses.replace(
        base,
        id="crit-3",
        version=3,
        status=CriteriaStatus.PENDING_APPROVAL,
        change_reason="Review only.",
        supersedes_id="crit-2",
    )
    async with client(rig) as http:
        body = (await http.get(PENDING, headers=LEAD_AUTH)).json()
    assert body["changes"] == []


async def test_no_pending_change_and_another_owner_are_a_404() -> None:
    rig = _world()
    async with client(rig) as http:
        none = await http.get(PENDING, headers=CLINICAL_AUTH)
    rig.units.criteria.versions["crit-3"] = _version(rig)
    async with client(rig) as http:
        other = await http.get(PENDING, headers=bearer(Role.OWNER, "prac-someone-else"))
    assert none.status_code == other.status_code == 404


# ----------------------------------------------------------------------------------- the history


async def test_the_history_gives_the_date_of_each_change_and_the_role_of_its_author() -> None:
    rig = _world()
    rig.units.criteria.versions["crit-3"] = _version(rig)
    async with client(rig) as http:
        response = await http.get(HISTORY, headers=OWNER_AUTH)

    assert response.status_code == 200, response.text
    entries = [entry["resource"] for entry in response.json()["entry"]]
    assert [(e["meta"]["versionId"], e["status"]) for e in entries] == [
        ("3", "pending-approval"),
        ("2", "current"),
        ("1", "superseded"),
    ]
    assert [(e["changedOn"], e["authorRole"]) for e in entries] == [
        ("2026-10-28", "Clinical lead, UCR"),
        ("2026-09-12", "Clinical lead, UCR"),
        ("2026-01-10", "Clinical lead, UCR"),
    ]


async def test_a_version_with_no_recorded_date_has_none() -> None:
    rig = _world()
    rig.units.criteria.versions["crit-1"] = dataclasses.replace(
        rig.units.criteria.versions["crit-1"], changed_on=None
    )
    async with client(rig) as http:
        entries = [
            e["resource"] for e in (await http.get(HISTORY, headers=OWNER_AUTH)).json()["entry"]
        ]
    assert entries[-1]["changedOn"] is None


async def test_an_advisor_reads_the_current_version_and_not_who_wrote_it_or_when() -> None:
    rig = _world()
    rig.units.criteria.versions["crit-3"] = _version(rig)
    async with client(rig) as http:
        response = await http.get(HISTORY, headers=bearer(Role.ADVISOR, "prac-adv"))

    assert response.status_code == 200, response.text
    entries = [entry["resource"] for entry in response.json()["entry"]]
    assert [e["status"] for e in entries] == ["current"]
    assert "authorRole" not in entries[0] and "changedOn" not in entries[0]
