"""The registration reads and actions (W7B A1 and A4), through the app on recording stand-ins: the
applicant's record, the applicant's services and status, the reviewer queue, the review overview,
the decision read, the test notification, the review request and the confirmation of details, the
two review steps that had no route, and the address lookup.

The rules each answer keeps: the applicant reads only their own registration (a registration of
another person, an unknown id and a role the route does not take are the one 404); a contact number
is never in a body (the last three digits only); the lead's reads name nothing the applicant has not
given; an action is keyed, replayed and audited. Sample values only: no patient data, no real
number."""

import dataclasses
from datetime import date, timedelta
from typing import Any

import pytest

from diucs.application.use_cases.registration_session import number_ending
from diucs.application.work import SCHEDULED, ScheduledWork, WorkKind
from diucs.domain.codes import (
    CriteriaStatus,
    PractitionerRoleCode,
    RegistrationStatus,
    Role,
    ScopeFlag,
    ServiceCategory,
)
from diucs.domain.model.people import Practitioner, PractitionerRole
from tests.support.w7b_rig import (
    APPLICANT_ROLE,
    INVITEE,
    LEAD,
    NOW,
    REGISTRATION,
    REPORTING_MOBILE,
    SERVICE,
    SERVICE_NAME,
    Rig,
    bearer,
    client,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")

KEY = {"Idempotency-Key": "w7b-views-key-0001"}
APPLICANT = bearer(Role.REPORTER, INVITEE, (SERVICE,))
OTHER_APPLICANT = bearer(Role.REPORTER, "prac-other", ("svc-other",))
LEAD_AUTH = bearer(Role.LEAD, LEAD)
RECORD = f"/registrations/{REGISTRATION}/record"
STATUS = f"/registrations/{REGISTRATION}/status"
OVERVIEW = f"/registrations/{REGISTRATION}/overview"
DECISION = f"/registrations/{REGISTRATION}/decision"
MINE = "/my/registrations"
QUEUE = "/registrations"
TEST_NOTIFICATION = f"/registrations/{REGISTRATION}/test-notification"
REVIEW_REQUEST = f"/registrations/{REGISTRATION}/review-request"
CONFIRM_DETAILS = f"/registrations/{REGISTRATION}/confirm-details"
ADDRESSES = "/addresses"


def _filled(status: RegistrationStatus = RegistrationStatus.SUBMITTED, **changes: Any) -> Rig:
    rig = Rig()
    rig.invite()
    rig.fill(status, **changes)
    rig.units.tenant_config.give_wording()
    return rig


def _no_number(text: str) -> bool:
    digits = "".join(char for char in text if char.isdigit())
    return REPORTING_MOBILE.replace(" ", "")[-8:] not in digits and "7700900456" not in digits


# ------------------------------------------------------------------- the applicant's record


async def test_the_applicant_reads_their_registration_step_by_step() -> None:
    rig = _filled(RegistrationStatus.DRAFT)
    async with client(rig) as http:
        response = await http.get(RECORD, headers=APPLICANT)

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["registrationId"], body["status"]) == (REGISTRATION, "draft")
    assert (body["serviceId"], body["serviceName"]) == (SERVICE, SERVICE_NAME)
    assert body["submittedAt"] == "2026-10-30T09:30:00Z"
    steps = body["steps"]
    assert list(steps) == ["organisation", "location", "service", "reporting", "api"]
    assert {key: step["state"] for key, step in steps.items()} == {
        "organisation": "complete",
        "location": "complete",
        "service": "complete",
        "reporting": "complete",
        "api": "complete",
    }
    assert steps["organisation"]["values"]["contactName"] == "Sam Patel"
    assert steps["location"]["values"]["open24h"] is True
    assert steps["service"]["values"]["reviewBy"] == "2027-01-01"
    assert steps["reporting"]["values"]["contactMobileEnding"] == "456"
    assert response.headers["cache-control"] == "no-store"


async def test_no_contact_number_or_address_is_in_the_record() -> None:
    rig = _filled(RegistrationStatus.DRAFT)
    async with client(rig) as http:
        response = await http.get(RECORD, headers=APPLICANT)

    reporting = response.json()["steps"]["reporting"]["values"]
    assert "contactMobile" not in reporting and "contactEmail" not in reporting
    assert reporting["hasContactEmail"] is False
    assert _no_number(response.text)


async def test_a_step_not_started_and_a_step_with_problems_are_told_apart() -> None:
    rig = _filled(RegistrationStatus.DRAFT)
    held = rig.units.registrations.held[REGISTRATION]
    draft = dict(held.draft)
    draft.pop("location")
    draft["organisation"] = {**draft["organisation"], "ods_code": ""}
    rig.units.registrations.held[REGISTRATION] = dataclasses.replace(held, draft=draft)
    async with client(rig) as http:
        steps = (await http.get(RECORD, headers=APPLICANT)).json()["steps"]

    assert steps["location"] == {"state": "not-started", "values": {}, "problems": []}
    assert steps["organisation"]["state"] == "needs-attention"
    assert steps["organisation"]["problems"] == [
        {"field": "odsCode", "message": "Enter the ODS code"}
    ]


async def test_another_persons_registration_an_unknown_id_and_other_roles_are_one_404() -> None:
    rig = _filled(RegistrationStatus.DRAFT)
    async with client(rig) as http:
        other = await http.get(RECORD, headers=OTHER_APPLICANT)
        unknown = await http.get("/registrations/nope/record", headers=APPLICANT)
        lead = await http.get(RECORD, headers=LEAD_AUTH)
        advisor = await http.get(RECORD, headers=bearer(Role.ADVISOR, "prac-adv"))

    assert {other.status_code, unknown.status_code, lead.status_code, advisor.status_code} == {404}
    assert other.content == unknown.content == lead.content


async def test_my_services_lists_only_the_applicants_own_registrations() -> None:
    rig = _filled(RegistrationStatus.SUBMITTED)
    rig.units.people.practitioners["prac-other"] = Practitioner(
        id="prac-other", active=True, display_name="Other", phone_hash=None
    )
    rig.units.people.roles["role-other"] = PractitionerRole(
        id="role-other",
        practitioner_id="prac-other",
        service_id="svc-other",
        code=PractitionerRoleCode.DUTY_MANAGER,
        active=True,
        channel=None,
        period_start=NOW - timedelta(days=1),
    )
    async with client(rig) as http:
        mine = await http.get(MINE, headers=APPLICANT)
        theirs = await http.get(MINE, headers=OTHER_APPLICANT)

    assert mine.json() == {
        "registrations": [
            {
                "registrationId": REGISTRATION,
                "serviceId": SERVICE,
                "serviceName": SERVICE_NAME,
                "status": "submitted",
                "submittedAt": "2026-10-30T09:30:00Z",
            }
        ]
    }
    assert theirs.json() == {"registrations": []}


# ---------------------------------------------------------------------- the applicant's status


async def test_the_status_page_gets_what_it_shows_and_nothing_else() -> None:
    rig = _filled(RegistrationStatus.APPROVED)
    rig.units.scheduled_work.held.append(
        ScheduledWork(
            "work-1", WorkKind.PROMPT_DUE, NOW + timedelta(hours=2), SERVICE, None, SCHEDULED
        )
    )
    rig.units.scheduled_work.held.append(
        ScheduledWork(
            "work-2", WorkKind.PROMPT_DUE, NOW + timedelta(hours=1), SERVICE, None, SCHEDULED
        )
    )
    async with client(rig) as http:
        response = await http.get(STATUS, headers=APPLICANT)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "approved"
    assert body["serviceName"] == SERVICE_NAME
    assert body["firstPromptAt"] == "2026-10-30T11:00:00Z"
    assert body["details"] == {
        "spoaPhone": "01305 123400",
        "criteriaOwner": "Clinical lead, UCR",
        "reportingPhoneEnding": "456",
    }
    for private in (TENANT_TEXT, "requesterRoleId", "ownerRoleId", "checks", "draft"):
        assert private not in response.text
    assert _no_number(response.text.replace("01305 123400", ""))


TENANT_TEXT = "example-icb"


async def test_a_note_comes_with_who_sent_it_and_a_reason_only_for_not_approved() -> None:
    rig = _filled(RegistrationStatus.NEEDS_CHANGES, note="Please add the call-back number.")
    rig.units.people.roles["role-reviewer"] = PractitionerRole(
        id="role-reviewer",
        practitioner_id=LEAD,
        service_id=None,
        code=PractitionerRoleCode.SHIFT_LEAD,
        active=True,
        channel=None,
        period_start=NOW - timedelta(days=1),
    )
    held = rig.units.registrations.held[REGISTRATION]
    rig.units.registrations.held[REGISTRATION] = dataclasses.replace(
        held, owner_role_id="role-reviewer"
    )
    async with client(rig) as http:
        sent_back = (await http.get(STATUS, headers=APPLICANT)).json()
    held = rig.units.registrations.held[REGISTRATION]
    rig.units.registrations.held[REGISTRATION] = dataclasses.replace(
        held, status=RegistrationStatus.NOT_APPROVED
    )
    async with client(rig) as http:
        refused = (await http.get(STATUS, headers=APPLICANT)).json()

    assert sent_back["note"] == "Please add the call-back number."
    assert sent_back["noteFrom"] == "Shift lead"
    assert sent_back["reason"] is None
    assert refused["reason"] == "Please add the call-back number."


async def test_the_status_of_another_persons_registration_is_a_404() -> None:
    rig = _filled(RegistrationStatus.SUBMITTED)
    async with client(rig) as http:
        response = await http.get(STATUS, headers=OTHER_APPLICANT)
    assert response.status_code == 404


# ------------------------------------------------------------------------- the reviewer queue


def _second_registration(rig: Rig, status: RegistrationStatus, name: str, minutes: int) -> None:
    from diucs.domain.model.registration import Registration, ScopeEntry

    held = rig.units.registrations.held[REGISTRATION]
    rig.units.registrations.held[f"reg-{name}"] = dataclasses.replace(
        held,
        id=f"reg-{name}",
        service_id=f"svc-{name}",
        status=status,
        submitted_at=NOW - timedelta(minutes=minutes),
    )
    rig.units.scope.entries_by_service[f"svc-{name}"] = ScopeEntry(
        f"svc-{name}", name, ServiceCategory.REABLEMENT, ScopeFlag.IN_PILOT, date(2026, 10, 1)
    )
    assert isinstance(rig.units.registrations.held[f"reg-{name}"], Registration)


async def test_the_queue_gives_the_tabs_with_counts_and_the_rows_of_the_tab_asked_for() -> None:
    rig = _filled(RegistrationStatus.SUBMITTED)
    _second_registration(rig, RegistrationStatus.IN_REVIEW, "East", 90)
    _second_registration(rig, RegistrationStatus.NEEDS_CHANGES, "North", 10)
    _second_registration(rig, RegistrationStatus.LIVE, "South", 600)
    async with client(rig) as http:
        waiting = await http.get(QUEUE, headers=LEAD_AUTH)
        sent_back = await http.get(f"{QUEUE}?tab=sent-back", headers=LEAD_AUTH)
        live = await http.get(f"{QUEUE}?tab=live", headers=LEAD_AUTH)
        bad = await http.get(f"{QUEUE}?tab=everything", headers=LEAD_AUTH)

    body = waiting.json()
    assert body["tab"] == "waiting"
    assert body["counts"] == {
        "waiting": 2,
        "sent-back": 1,
        "approved": 0,
        "live": 1,
        "not-approved": 0,
    }
    assert [tab["key"] for tab in body["tabs"]] == [
        "waiting",
        "sent-back",
        "approved",
        "live",
        "not-approved",
    ]
    assert body["tabs"][0] == {"key": "waiting", "label": "Waiting for review", "count": 2}
    # Oldest submission first.
    assert [row["serviceName"] for row in body["registrations"]] == ["East", SERVICE_NAME]
    row = body["registrations"][1]
    assert row["registrationId"] == REGISTRATION
    assert row["status"] == "submitted"
    assert row["registeredBy"] == {"role": "Duty manager", "contactName": "Sam Patel"}
    assert [r["serviceName"] for r in sent_back.json()["registrations"]] == ["North"]
    assert [r["serviceName"] for r in live.json()["registrations"]] == ["South"]
    assert bad.status_code == 400


async def test_an_invited_or_drafting_registration_is_not_in_the_queue() -> None:
    rig = _filled(RegistrationStatus.DRAFT)
    async with client(rig) as http:
        body = (await http.get(QUEUE, headers=LEAD_AUTH)).json()
    assert body["counts"]["waiting"] == 0
    assert body["registrations"] == []


# ------------------------------------------------------------------------ the review overview


async def test_the_overview_gives_the_checks_who_registered_and_the_numbers_to_tell_apart() -> None:
    rig = _filled(RegistrationStatus.IN_REVIEW)
    async with client(rig) as http:
        response = await http.get(OVERVIEW, headers=LEAD_AUTH)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "in-review"
    assert [check["name"] for check in body["checks"]] == [
        "ods-code",
        "organisation-name",
        "address-area",
        "reporting-phone",
        "owner-email",
    ]
    assert body["checks"][0] == {
        "name": "ods-code",
        "passed": True,
        "ok": True,
        "message": "ODS code found, active, NHS organisation",
        "explainedNote": None,
    }
    assert body["automaticOk"] is False  # the reporting number is not the invited one
    assert body["checks"][3]["passed"] is False
    assert body["callbackConfirmed"] is False
    assert body["scope"] is None
    assert body["missing"] == [
        "Automatic checks passed or explained",
        "Call-back done",
        "Scope decided: in pilot",
        "Criteria second approval",
    ]
    assert body["registeredBy"] == {
        "role": "Duty manager",
        "contactName": "Sam Patel",
        "organisationName": "Community Response Ltd",
    }
    assert body["applicantNumbers"] == [
        {"label": "Reporting phone", "ending": "456"},
        {"label": "Organisation contact", "ending": "111"},
        {"label": "Service phone for the SPOA", "ending": "400"},
    ]
    assert body["callBack"] == {
        "numberToCall": None,
        "directoryName": "Sample directory",
        "pathwayName": "Sample urgent care",
    }
    assert _no_number(response.text.replace("01305 000111", "").replace("01305 123400", ""))
    for number in ("01305 000111", "01305 123400", REPORTING_MOBILE):
        assert number not in response.text


async def test_the_overview_names_no_directory_or_pathway_when_the_tenant_has_no_wording() -> None:
    rig = _filled(RegistrationStatus.IN_REVIEW)
    rig.units.tenant_config.config = None
    async with client(rig) as http:
        body = (await http.get(OVERVIEW, headers=LEAD_AUTH)).json()
    assert body["callBack"] == {"numberToCall": None, "directoryName": None, "pathwayName": None}


async def test_a_registration_the_applicant_has_not_submitted_is_not_open_to_the_reviewer() -> None:
    rig = _filled(RegistrationStatus.DRAFT)
    async with client(rig) as http:
        response = await http.get(OVERVIEW, headers=LEAD_AUTH)
    assert response.status_code == 409


# ---------------------------------------------------------------------------- the decision


async def test_the_decision_names_what_is_missing_the_approvals_the_test_and_the_timeline() -> None:
    rig = _filled(RegistrationStatus.IN_REVIEW)
    async with client(rig) as http:
        response = await http.get(DECISION, headers=LEAD_AUTH)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "in-review"
    assert body["canApprove"] is False
    assert body["missing"] == [
        "Automatic checks passed or explained",
        "Call-back done",
        "Scope decided: in pilot",
        "Criteria second approval",
    ]
    assert body["approvals"] == [
        {"key": "automatic", "label": "Automatic checks passed or explained", "done": False},
        {"key": "callback", "label": "Call-back done", "done": False},
        {"key": "scope", "label": "Scope decided: in pilot", "done": False},
        {"key": "criteria", "label": "Criteria second approval", "done": False},
    ]
    assert body["test"] == {"sentAt": None, "channel": None}
    assert [event["event"] for event in body["timeline"]] == ["invited", "submitted"]


async def test_a_decision_with_every_check_done_can_be_approved() -> None:
    from diucs.domain.rules.registration import ApprovalChecks

    rig = _filled(RegistrationStatus.IN_REVIEW)
    held = rig.units.registrations.held[REGISTRATION]
    rig.units.registrations.held[REGISTRATION] = dataclasses.replace(
        held, checks=ApprovalChecks(True, True, ScopeFlag.IN_PILOT, True)
    )
    rig.units.criteria.current[SERVICE] = type("C", (), {"status": CriteriaStatus.CURRENT})()
    # The automatic checks are re-judged from what is stored: the reporting number is explained.
    notes = {**held.draft.get("check_notes", {}), "reporting-phone": "Phoned and agreed."}
    registration = rig.units.registrations.held[REGISTRATION]
    rig.units.registrations.held[REGISTRATION] = dataclasses.replace(
        registration, draft={**registration.draft, "check_notes": notes}
    )
    async with client(rig) as http:
        body = (await http.get(DECISION, headers=LEAD_AUTH)).json()

    assert body["missing"] == []
    assert body["canApprove"] is True
    assert all(item["done"] for item in body["approvals"])


# ------------------------------------------------------------------------------ the actions


async def test_a_test_notification_is_queued_to_the_applicant_by_the_channel_they_chose() -> None:
    rig = _filled(RegistrationStatus.APPROVED)
    async with client(rig) as http:
        response = await http.post(TEST_NOTIFICATION, headers={**KEY, **APPLICANT})

    assert response.status_code == 200, response.text
    assert response.json() == {"sentAt": "2026-10-30T10:00:00Z", "channel": "text"}
    sent = rig.units.communications.sent
    assert [(c.message_id, c.channel.value, c.recipient_role_id, c.about_id) for c in sent] == [
        ("T1", "text", APPLICANT_ROLE, SERVICE)
    ]
    assert "sealed" in str(rig.units.outbox.messages[0].payload)
    assert REPORTING_MOBILE not in str(rig.units.outbox.messages[0].payload)
    marker = rig.units.registrations.held[REGISTRATION].draft["test_notification"]
    assert marker == {"sent_at": "2026-10-30T10:00:00Z", "channel": "text"}
    assert rig.units.audit.entries[-1].use_case == "SendTestNotification"


async def test_the_lead_may_send_the_test_again_and_a_second_press_inside_a_minute_is_a_409() -> (
    None
):
    rig = _filled(RegistrationStatus.IN_REVIEW)
    async with client(rig) as http:
        first = await http.post(TEST_NOTIFICATION, headers={**KEY, **LEAD_AUTH})
        again = await http.post(
            TEST_NOTIFICATION, headers={"Idempotency-Key": "another-key-0002", **LEAD_AUTH}
        )
        rig.clock.advance(timedelta(minutes=2))
        later = await http.post(
            TEST_NOTIFICATION, headers={"Idempotency-Key": "another-key-0003", **LEAD_AUTH}
        )

    assert (first.status_code, again.status_code, later.status_code) == (200, 409, 200)
    assert len(rig.units.communications.sent) == 2


async def test_a_test_notification_before_the_registration_is_submitted_is_refused() -> None:
    rig = _filled(RegistrationStatus.DRAFT)
    async with client(rig) as http:
        response = await http.post(TEST_NOTIFICATION, headers={**KEY, **APPLICANT})
    assert response.status_code == 409
    assert rig.units.communications.sent == []


async def test_the_same_key_sends_one_test_not_two() -> None:
    rig = _filled(RegistrationStatus.APPROVED)
    async with client(rig) as http:
        await http.post(TEST_NOTIFICATION, headers={**KEY, **APPLICANT})
        rig.clock.advance(timedelta(minutes=5))
        replay = await http.post(TEST_NOTIFICATION, headers={**KEY, **APPLICANT})
    assert replay.status_code == 200
    assert len(rig.units.communications.sent) == 1


async def test_another_applicant_cannot_send_a_test_and_nothing_is_queued() -> None:
    rig = _filled(RegistrationStatus.APPROVED)
    async with client(rig) as http:
        response = await http.post(TEST_NOTIFICATION, headers={**KEY, **OTHER_APPLICANT})
    assert response.status_code == 404
    assert rig.units.communications.sent == []
    assert rig.units.outbox.messages == []


async def test_a_review_request_is_recorded_and_may_be_made_again() -> None:
    rig = _filled(RegistrationStatus.SUBMITTED)
    async with client(rig) as http:
        first = await http.post(REVIEW_REQUEST, headers={**KEY, **APPLICANT})
        second = await http.post(
            REVIEW_REQUEST, headers={"Idempotency-Key": "other-key-0009", **APPLICANT}
        )

    assert first.status_code == second.status_code == 200
    assert first.json() == {"requestedAt": "2026-10-30T10:00:00Z"}
    held = rig.units.registrations.held[REGISTRATION]
    assert held.draft["review_request"] == {"requested_at": "2026-10-30T10:00:00Z"}
    assert held.status is RegistrationStatus.SUBMITTED


async def test_a_review_cannot_be_asked_for_before_submission_or_after_the_decision() -> None:
    for status in (RegistrationStatus.DRAFT, RegistrationStatus.LIVE):
        rig = _filled(status)
        async with client(rig) as http:
            response = await http.post(REVIEW_REQUEST, headers={**KEY, **APPLICANT})
        assert response.status_code == 409, status


async def test_confirming_the_details_of_a_registration_to_reverify_makes_it_live_again() -> None:
    rig = _filled(RegistrationStatus.REVERIFY)
    async with client(rig) as http:
        response = await http.post(CONFIRM_DETAILS, headers={**KEY, **APPLICANT})

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "live", "confirmedAt": "2026-10-30T10:00:00Z"}
    held = rig.units.registrations.held[REGISTRATION]
    assert held.status is RegistrationStatus.LIVE
    assert rig.units.audit.entries[-1].use_case == "ConfirmRegistrationDetails"


async def test_the_details_cannot_be_confirmed_unless_a_check_is_due() -> None:
    rig = _filled(RegistrationStatus.LIVE)
    async with client(rig) as http:
        response = await http.post(CONFIRM_DETAILS, headers={**KEY, **APPLICANT})
    assert response.status_code == 409


# ------------------------------------------------------------- the two review steps with no route


async def test_the_lead_starts_a_review_and_the_registration_is_in_review() -> None:
    rig = _filled(RegistrationStatus.SUBMITTED)
    async with client(rig) as http:
        response = await http.post(
            f"/fhir/Task/{REGISTRATION}/$start-review", headers={**KEY, **LEAD_AUTH}
        )

    assert response.status_code == 200, response.text
    assert response.json()["businessStatus"]["coding"][0]["code"] == "in-review"
    assert rig.units.registrations.held[REGISTRATION].status is RegistrationStatus.IN_REVIEW


async def test_a_failed_check_is_explained_and_a_check_that_passed_is_not() -> None:
    rig = _filled(RegistrationStatus.IN_REVIEW)

    def explain(check: str, note: str = "Phoned and agreed.") -> dict[str, Any]:
        return {
            "resourceType": "Parameters",
            "parameter": [
                {"name": "check", "valueCode": check},
                {"name": "note", "valueString": note},
            ],
        }

    async with client(rig) as http:
        explained = await http.post(
            f"/fhir/Task/{REGISTRATION}/$explain-check",
            json=explain("reporting-phone"),
            headers={**KEY, **LEAD_AUTH},
        )
        passed = await http.post(
            f"/fhir/Task/{REGISTRATION}/$explain-check",
            json=explain("ods-code"),
            headers={"Idempotency-Key": "other-key-0010", **LEAD_AUTH},
        )
        unknown = await http.post(
            f"/fhir/Task/{REGISTRATION}/$explain-check",
            json=explain("favourite-colour"),
            headers={"Idempotency-Key": "other-key-0011", **LEAD_AUTH},
        )

    assert explained.status_code == 200, explained.text
    assert explained.json()["parameter"][0] == {"name": "automaticOk", "valueBoolean": False}
    assert passed.status_code == 409
    assert unknown.status_code == 400


# ----------------------------------------------------------------------- the address lookup


async def test_an_address_lookup_gives_at_most_twenty_labels_and_never_the_postcode_back() -> None:
    from diucs.adapters.testing.fixed_geo import FixedGeocoder
    from diucs.application.ports.outbound.geo import AddressCandidate, LatLon

    rig = _filled(RegistrationStatus.DRAFT)
    candidates = [
        AddressCandidate(
            f"10001234{n:04d}", f"{n} Sample Road", "Weymouth", "DT4 8XX", LatLon(1, 1)
        )
        for n in range(25)
    ]
    rig.geocoder = FixedGeocoder({"DT4 8XX": candidates})
    async with client(rig) as http:
        response = await http.get(f"{ADDRESSES}?postcode=dt48xx", headers=APPLICANT)

    assert response.status_code == 200, response.text
    addresses = response.json()["addresses"]
    assert len(addresses) == 20
    assert addresses[0] == {"id": "100012340000", "label": "0 Sample Road, Weymouth"}
    assert "DT4" not in response.text


async def test_a_postcode_that_is_not_one_is_a_400_and_an_unknown_one_is_an_empty_list() -> None:
    rig = _filled(RegistrationStatus.DRAFT)
    async with client(rig) as http:
        bad = await http.get(f"{ADDRESSES}?postcode=hello", headers=APPLICANT)
        missing = await http.get(ADDRESSES, headers=APPLICANT)
        none = await http.get(f"{ADDRESSES}?postcode=DT4%208XX", headers=APPLICANT)

    assert bad.status_code == missing.status_code == 400
    assert "hello" not in bad.text
    assert none.json() == {"addresses": []}


async def test_a_lookup_that_cannot_answer_is_a_503_and_not_an_empty_list() -> None:
    from diucs.application.ports.outbound.lookups import TransientLookupError

    class _Down:
        async def find_addresses(self, postcode: str) -> list[Any]:
            raise TransientLookupError

    rig = _filled(RegistrationStatus.DRAFT)
    rig.geocoder = _Down()  # type: ignore[assignment]
    async with client(rig) as http:
        response = await http.get(f"{ADDRESSES}?postcode=DT4%208XX", headers=APPLICANT)
    assert response.status_code == 503


async def test_only_a_reporter_looks_up_an_address() -> None:
    rig = _filled(RegistrationStatus.DRAFT)
    async with client(rig) as http:
        lead = await http.get(f"{ADDRESSES}?postcode=DT4%208XX", headers=LEAD_AUTH)
    assert lead.status_code == 404


def test_the_ending_of_a_number_is_its_last_three_digits() -> None:
    assert number_ending("+447700900456") == "456"
    assert number_ending("07700 900 456") == "456"
