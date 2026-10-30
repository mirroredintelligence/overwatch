"""The shift lead's reads and actions (W7B C), through the app on recording stand-ins: the overview
(chasing, figures getting old, covering, the counts), the reminder, the reporter post of each
service, the state of a suspension, the closed flags, the phones, the invitations with their steps,
resend and switch to text, and the test prompt.

The rules each answer keeps: only the shift lead reaches them (any other role is the 404 a missing
record gets); a mobile number is never in a body (the last three or four digits stand for it); a
service or an invitation of another tenant is a 404 (the integration test); a suspended service is
chased by nobody; a reminder is sent only when one is waiting; a test message goes out once a
minute. Sample values only."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from diucs.application.use_cases.missed_report_ladder import LadderStepResult
from diucs.application.work import SCHEDULED, ScheduledWork, WorkKind
from diucs.domain.codes import (
    Channel,
    PractitionerRoleCode,
    RegistrationStatus,
    ReportFlagReason,
    Role,
)
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.flags import ReportFlag
from diucs.domain.model.people import PractitionerRole
from diucs.domain.rules.identity_policy import PinState
from tests.support.w7b_rig import (
    DEVICE,
    INVITATION,
    INVITEE,
    LEAD,
    NOW,
    SERVICE,
    SERVICE_NAME,
    Rig,
    bearer,
    client,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")

LEAD_AUTH = bearer(Role.LEAD, LEAD)
KEY = {"Idempotency-Key": "w7b-lead-key-0001", "Content-Type": "application/json"}


def _world() -> Rig:
    rig = Rig()
    rig.lead_world()
    return rig


def _digits(text: str) -> bool:
    """True when no full mobile number is in the text."""
    return "7700900421" not in text and "7700900777" not in text and "07700 900" not in text


# ------------------------------------------------------------------------------- the overview


async def test_the_overview_gives_who_to_chase_what_is_getting_old_and_who_is_covering() -> None:
    rig = _world()
    async with client(rig) as http:
        response = await http.get("/lead/overview", headers=LEAD_AUTH)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["chasing"] == [
        {
            "serviceId": "svc-a",
            "name": "Ward A",
            "dueAt": "2026-10-30T08:00:00Z",
            "overdueMinutes": 120,
            "lastValueText": "2 beds",
            "ladder": [
                {"step": "prompt", "at": "2026-10-30T08:00:00Z", "done": True},
                {"step": "reminder", "at": "2026-10-30T08:30:00Z", "done": True},
                {"step": "phone-task", "at": "2026-10-30T09:00:00Z", "done": True},
                {"step": "escalate", "at": "2026-10-30T09:30:00Z", "done": False},
            ],
        }
    ]
    assert body["gettingOld"] == [
        {
            "serviceId": "svc-b",
            "name": "Ward B",
            "reportedAt": "2026-10-30T07:30:00Z",
            "nextDueAt": "2026-10-31T00:00:00Z",
            "status": "accepting",
        }
    ]
    assert body["covering"] == [
        {
            "serviceId": "svc-a",
            "name": "Ward A",
            "numberEnding": "0777",
            "until": "2026-10-31T10:00:00Z",
        }
    ]
    assert body["counts"] == {
        "accepting": 1,
        "limited": 0,
        "notAccepting": 0,
        "overCapacity": 0,
        "notUpdated": 2,
    }
    assert body["reportingToday"] == 3
    assert response.headers["cache-control"] == "no-store"
    assert _digits(response.text)


async def test_a_suspended_service_is_chased_by_nobody_and_is_not_getting_old() -> None:
    rig = _world()
    rig.units.capacity.reports["svc-c"] = CapacityReport(
        id="obs-old",
        service_id="svc-c",
        value=1,
        measure=rig.units.capacity.reports["svc-c"].measure,
        effective_at=datetime(2026, 10, 29, 6, 0, tzinfo=UTC),
        source=rig.units.capacity.reports["svc-c"].source,
        report_type=rig.units.capacity.reports["svc-c"].report_type,
    )
    async with client(rig) as http:
        body = (await http.get("/lead/overview", headers=LEAD_AUTH)).json()

    assert [item["serviceId"] for item in body["chasing"]] == ["svc-a"]
    assert [item["serviceId"] for item in body["gettingOld"]] == ["svc-b"]


async def test_nothing_to_chase_is_an_empty_list_and_not_a_missing_one() -> None:
    rig = _world()
    fresh = datetime(2026, 10, 30, 9, 58, tzinfo=UTC)
    for service in ("svc-a", "svc-b"):
        report = rig.units.capacity.reports[service]
        rig.units.capacity.reports[service] = CapacityReport(
            report.id,
            service,
            report.value,
            report.measure,
            fresh,
            report.source,
            report.report_type,
        )
    async with client(rig) as http:
        body = (await http.get("/lead/overview", headers=LEAD_AUTH)).json()

    assert body["chasing"] == [] and body["gettingOld"] == []
    assert set(body) == {"chasing", "gettingOld", "covering", "counts", "reportingToday"}


async def test_a_cover_made_before_the_number_was_kept_shows_a_blank_ending() -> None:
    rig = _world()
    del rig.units.contacts.phones["cover-role-rep-a"]
    async with client(rig) as http:
        body = (await http.get("/lead/overview", headers=LEAD_AUTH)).json()
    assert body["covering"][0]["numberEnding"] == "----"


# --------------------------------------------------------------------------------- the reminder


class _Ladder:
    def __init__(self) -> None:
        self.seen: list[Any] = []

    async def execute(self, command: Any) -> LadderStepResult:
        self.seen.append(command)
        return LadderStepResult("reminded")


async def test_a_reminder_runs_the_step_that_is_waiting_for_that_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from diucs.adapters.inbound.fhir_rest import routes_lead_views

    ladder = _Ladder()
    monkeypatch.setattr(routes_lead_views, "build_ladder", lambda container: ladder)
    rig = _world()
    rig.units.scheduled_work.held.append(
        ScheduledWork(
            "work-b", WorkKind.REMINDER, NOW + timedelta(minutes=20), "svc-b", None, SCHEDULED
        )
    )
    async with client(rig) as http:
        response = await http.post("/lead/services/svc-b/remind", headers={**KEY, **LEAD_AUTH})

    assert response.status_code == 200, response.text
    assert response.json() == {"reminded": True}
    assert [command.work_id for command in ladder.seen] == ["work-b"]


async def test_a_reminder_already_sent_an_unknown_service_and_no_key_are_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from diucs.adapters.inbound.fhir_rest import routes_lead_views

    ladder = _Ladder()
    monkeypatch.setattr(routes_lead_views, "build_ladder", lambda container: ladder)
    rig = _world()
    async with client(rig) as http:
        sent = await http.post("/lead/services/svc-a/remind", headers={**KEY, **LEAD_AUTH})
        unknown = await http.post("/lead/services/svc-x/remind", headers={**KEY, **LEAD_AUTH})
        no_key = await http.post(
            "/lead/services/svc-a/remind",
            headers={"Content-Type": "application/json", **LEAD_AUTH},
        )

    assert (sent.status_code, unknown.status_code, no_key.status_code) == (409, 404, 400)
    assert ladder.seen == []


# ----------------------------------------------------------------------- the reporter of a service


async def test_the_reporter_post_of_each_service_is_given_with_its_role_id() -> None:
    rig = _world()
    async with client(rig) as http:
        every = await http.get("/lead/reporters", headers=LEAD_AUTH)
        one = await http.get("/lead/reporters?service=svc-b", headers=LEAD_AUTH)

    assert every.status_code == 200, every.text
    assert every.json() == {
        "reporters": [
            {
                "serviceId": "svc-a",
                "serviceName": "Ward A",
                "roleId": "role-rep-a",
                "role": "Duty manager",
                "channel": "text",
                "numberEnding": "0421",
                "coveredUntil": "2026-10-31T10:00:00Z",
            },
            {
                "serviceId": "svc-b",
                "serviceName": "Ward B",
                "roleId": "role-rep-b",
                "role": "Duty manager",
                "channel": "text",
                "numberEnding": "0421",
                "coveredUntil": None,
            },
        ]
    }
    assert [r["serviceId"] for r in one.json()["reporters"]] == ["svc-b"]
    assert _digits(every.text)


async def test_a_service_that_is_not_there_has_no_reporters_and_is_a_404() -> None:
    rig = _world()
    async with client(rig) as http:
        response = await http.get("/lead/reporters?service=svc-x", headers=LEAD_AUTH)
    assert response.status_code == 404


# ------------------------------------------------------------------------------ the suspension


async def test_a_suspension_says_since_when_why_how_many_expired_and_whom_to_phone() -> None:
    rig = _world()
    async with client(rig) as http:
        suspended = await http.get("/lead/services/svc-c/suspension", headers=LEAD_AUTH)
        active = await http.get("/lead/services/svc-a/suspension", headers=LEAD_AUTH)
        unknown = await http.get("/lead/services/svc-x/suspension", headers=LEAD_AUTH)

    assert suspended.json() == {
        "suspended": True,
        "since": "2026-10-30T08:12:00Z",
        "reason": "closed-unexpectedly",
        "expiredRequests": 2,
        "registerNumber": "01305 123400",
    }
    assert active.json() == {
        "suspended": False,
        "since": None,
        "reason": None,
        "expiredRequests": None,
        "registerNumber": None,
    }
    assert unknown.status_code == 404


# ---------------------------------------------------------------------------- the closed flags


def _flag(rig: Rig, status: str, outcome: str | None) -> None:
    resolved = None if status == "open" else NOW - timedelta(minutes=10)
    rig.units.flags.report_flags[f"flag-{status}"] = ReportFlag(
        id=f"flag-{status}",
        report_id="obs-svc-a",
        service_id="svc-a",
        reason=ReportFlagReason.OUT_OF_RANGE_TWICE,
        status=status,
        created_at=NOW - timedelta(hours=1),
        resolved_at=resolved,
        outcome=outcome,
        resolved_by=None if resolved is None else LEAD,
    )


async def test_the_closed_flags_are_listed_with_how_they_were_closed() -> None:
    rig = _world()
    _flag(rig, "checked", "checked")
    _flag(rig, "accepted", "accepted")
    _flag(rig, "open", None)
    async with client(rig) as http:
        closed = await http.get("/admin/report-flags?status=closed", headers=LEAD_AUTH)
        bad = await http.get("/admin/report-flags?status=everything", headers=LEAD_AUTH)

    assert closed.status_code == 200, closed.text
    body = closed.json()
    assert body["total"] == 2
    resources = {entry["resource"]["id"]: entry["resource"] for entry in body["entry"]}
    assert set(resources) == {"flag-checked", "flag-accepted"}
    checked = resources["flag-checked"]
    assert checked["status"] == "inactive"
    assert checked["outcome"] == "checked"
    assert checked["subject"] == {"reference": "HealthcareService/svc-a", "display": "Ward A"}
    assert checked["period"] == {"start": "2026-10-30T09:00:00Z", "end": "2026-10-30T09:50:00Z"}
    assert "prac" not in closed.text
    assert bad.status_code == 400


# ---------------------------------------------------------------------------------- the phones


async def test_the_phones_are_grouped_by_who_holds_the_service_now() -> None:
    rig = _world()
    async with client(rig) as http:
        response = await http.get("/lead/phones", headers=LEAD_AUTH)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "phones": [
            {
                "phoneEnding": "421",
                "role": "Duty manager",
                "services": [{"id": "svc-b", "name": "Ward B"}],
                "channel": "text",
                "lastSeen": "2026-10-30T07:30:00Z",
            },
            {
                "phoneEnding": "777",
                "role": "Cover",
                "services": [{"id": "svc-a", "name": "Ward A"}],
                "channel": "text",
                "lastSeen": "2026-10-30T06:30:00Z",
            },
        ]
    }
    assert _digits(response.text)


async def test_a_phone_that_holds_several_services_is_one_row() -> None:
    rig = _world()
    rig.units.people.roles["role-rep-a"] = PractitionerRole(
        id="role-rep-a",
        practitioner_id="prac-rep-a",
        service_id="svc-a",
        code=PractitionerRoleCode.DUTY_MANAGER,
        active=True,
        channel=Channel.TEXT,
        period_start=NOW - timedelta(days=30),
    )
    async with client(rig) as http:
        phones = (await http.get("/lead/phones", headers=LEAD_AUTH)).json()["phones"]
    assert [(p["phoneEnding"], [s["id"] for s in p["services"]]) for p in phones] == [
        ("421", ["svc-a", "svc-b"])
    ]


# ------------------------------------------------------------------------------- the invitations


def _invited(status: RegistrationStatus = RegistrationStatus.DRAFT) -> Rig:
    rig = Rig()
    rig.invite()
    rig.fill(status)
    rig.units.devices.held[(INVITEE, DEVICE)] = {
        "revoked": False,
        "pending": False,
        "verified_at": NOW - timedelta(minutes=10),
        "at": NOW - timedelta(minutes=30),
    }
    return rig


async def test_an_invitation_says_how_far_the_set_up_has_got() -> None:
    rig = _invited()
    async with client(rig) as http:
        response = await http.get("/lead/invitations", headers=LEAD_AUTH)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "items": [
            {
                "id": INVITATION,
                "serviceName": SERVICE_NAME,
                "role": "Duty manager",
                "steps": {
                    "invited": True,
                    "numberChecked": True,
                    "channelChosen": True,
                    "installed": True,
                    "notificationsOn": False,
                    "pinSet": False,
                    "firstReport": False,
                },
                "invitedAt": "2026-10-30T09:00:00Z",
                "lastSeen": "2026-10-30T09:50:00Z",
                "firstReportAt": None,
            }
        ]
    }
    assert _digits(response.text)


async def test_a_pin_a_push_subscription_and_a_first_report_complete_the_steps() -> None:
    rig = _invited(RegistrationStatus.LIVE)
    rig.units.pins.held[(INVITEE, DEVICE)] = ("hash", PinState())
    from diucs.application.ports.outbound.messaging import PushSubscription

    rig.units.push_subscriptions.held[DEVICE] = PushSubscription(
        device_id=DEVICE,
        practitioner_id=INVITEE,
        subscription={"endpoint": "https://push.example/x", "keys": {"p256dh": "a", "auth": "b"}},
        saved_at=NOW,
    )
    from diucs.domain.codes import Measure, ReportSource, ReportType

    rig.units.capacity.reports[SERVICE] = CapacityReport(
        "obs-1",
        SERVICE,
        4,
        Measure.REFERRALS_ACCEPTABLE,
        NOW - timedelta(minutes=5),
        ReportSource.TEXT,
        ReportType.NUMBER,
    )
    async with client(rig) as http:
        item = (await http.get("/lead/invitations", headers=LEAD_AUTH)).json()["items"][0]

    assert all(item["steps"].values())
    assert item["firstReportAt"] == "2026-10-30T09:55:00Z"


async def test_an_invitation_with_nothing_done_beyond_the_invite_says_so() -> None:
    rig = Rig()
    rig.invite()
    async with client(rig) as http:
        item = (await http.get("/lead/invitations", headers=LEAD_AUTH)).json()["items"][0]

    assert item["steps"] == {
        "invited": True,
        "numberChecked": False,
        "channelChosen": False,
        "installed": False,
        "notificationsOn": False,
        "pinSet": False,
        "firstReport": False,
    }
    assert item["lastSeen"] == item["invitedAt"]


async def test_the_invitation_is_sent_again_while_the_registration_is_invited() -> None:
    rig = Rig()
    rig.invite()
    async with client(rig) as http:
        response = await http.post(
            f"/lead/invitations/{INVITATION}/resend", headers={**KEY, **LEAD_AUTH}
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["invitationId"] == INVITATION
    assert body["expiresAt"] == "2026-11-01T10:00:00Z"
    assert [c.message_id for c in rig.units.communications.sent] == ["I1"]


async def test_an_invitation_cannot_be_sent_again_once_the_applicant_has_begun() -> None:
    rig = _invited(RegistrationStatus.DRAFT)
    async with client(rig) as http:
        response = await http.post(
            f"/lead/invitations/{INVITATION}/resend", headers={**KEY, **LEAD_AUTH}
        )
    assert response.status_code == 409
    assert rig.units.communications.sent == []


async def test_a_reporter_is_switched_to_text() -> None:
    rig = Rig()
    rig.invite()
    rig.units.people.roles["role-applicant"] = PractitionerRole(
        id="role-applicant",
        practitioner_id=INVITEE,
        service_id=SERVICE,
        code=PractitionerRoleCode.DUTY_MANAGER,
        active=True,
        channel=Channel.PUSH,
        period_start=NOW - timedelta(hours=1),
    )
    async with client(rig) as http:
        response = await http.post(
            f"/lead/invitations/{INVITATION}/switch-to-text", headers={**KEY, **LEAD_AUTH}
        )

    assert response.status_code == 200, response.text
    assert response.json() == {"channel": "text"}
    assert rig.units.people.roles["role-applicant"].channel is Channel.TEXT
    assert rig.units.audit.entries[-1].use_case == "SwitchReporterToText"


async def test_a_reporter_with_no_number_held_cannot_be_switched_to_text() -> None:
    rig = Rig()
    rig.invite()
    del rig.units.contacts.phones["role-applicant"]
    async with client(rig) as http:
        response = await http.post(
            f"/lead/invitations/{INVITATION}/switch-to-text", headers={**KEY, **LEAD_AUTH}
        )
    assert response.status_code == 409


async def test_an_unknown_invitation_is_a_404_for_every_action() -> None:
    rig = Rig()
    rig.invite()
    async with client(rig) as http:
        resend = await http.post("/lead/invitations/nope/resend", headers={**KEY, **LEAD_AUTH})
        switch = await http.post(
            "/lead/invitations/nope/switch-to-text", headers={**KEY, **LEAD_AUTH}
        )
    assert resend.status_code == switch.status_code == 404


# ------------------------------------------------------------------------------ the test prompt


async def test_a_test_prompt_goes_to_the_services_reporter_by_their_channel() -> None:
    rig = _world()
    async with client(rig) as http:
        response = await http.post("/lead/services/svc-b/test-prompt", headers={**KEY, **LEAD_AUTH})

    assert response.status_code == 200, response.text
    assert response.json() == {"channel": "text", "numberEnding": "0421"}
    sent = rig.units.communications.sent
    assert [(c.message_id, c.recipient_role_id, c.about_id) for c in sent] == [
        ("T1", "role-rep-b", "svc-b")
    ]
    assert rig.units.audit.entries[-1].use_case == "SendLeadTestPrompt"
    assert "7700900421" not in str(rig.units.outbox.messages[0].payload)


async def test_a_test_prompt_for_a_covered_post_names_the_covers_number_not_the_original() -> None:
    # F6B: the text goes to whoever holds the post now, so the lead is shown the cover's ending
    # (0777) and the check is on the cover's number.
    rig = _world()
    async with client(rig) as http:
        response = await http.post("/lead/services/svc-a/test-prompt", headers={**KEY, **LEAD_AUTH})

    assert response.status_code == 200, response.text
    assert response.json() == {"channel": "text", "numberEnding": "0777"}
    assert [c.recipient_role_id for c in rig.units.communications.sent] == ["role-rep-a"]


async def test_a_test_prompt_for_a_covered_post_with_no_cover_number_is_refused() -> None:
    rig = _world()
    del rig.units.contacts.phones["cover-role-rep-a"]
    async with client(rig) as http:
        response = await http.post("/lead/services/svc-a/test-prompt", headers={**KEY, **LEAD_AUTH})

    assert response.status_code == 400, response.text
    assert rig.units.communications.sent == []


async def test_an_email_test_prompt_for_a_covered_post_is_refused_not_sent_to_the_original() -> (
    None
):
    rig = _world()
    rig.units.contacts.emails["role-rep-a"] = "post.holder@example.test"
    async with client(rig) as http:
        response = await http.post(
            "/lead/services/svc-a/test-prompt",
            json={"channel": "email"},
            headers={**KEY, **LEAD_AUTH},
        )

    assert response.status_code == 400, response.text
    assert rig.units.communications.sent == []


async def test_a_second_test_prompt_in_one_minute_is_a_409_and_the_next_minute_is_not() -> None:
    rig = _world()
    async with client(rig) as http:
        first = await http.post("/lead/services/svc-b/test-prompt", headers={**KEY, **LEAD_AUTH})
        second = await http.post(
            "/lead/services/svc-b/test-prompt",
            headers={**KEY, "Idempotency-Key": "w7b-lead-key-0002", **LEAD_AUTH},
        )
        rig.clock.advance(timedelta(minutes=2))
        third = await http.post(
            "/lead/services/svc-b/test-prompt",
            headers={**KEY, "Idempotency-Key": "w7b-lead-key-0003", **LEAD_AUTH},
        )

    assert (first.status_code, second.status_code, third.status_code) == (200, 409, 200)
    assert len(rig.units.communications.sent) == 2


async def test_a_test_prompt_by_a_channel_the_reporter_has_no_contact_for_is_a_400() -> None:
    rig = _world()
    async with client(rig) as http:
        response = await http.post(
            "/lead/services/svc-b/test-prompt",
            json={"channel": "email"},
            headers={"Idempotency-Key": "w7b-lead-key-0004", **LEAD_AUTH},
        )
    assert response.status_code == 400
    assert rig.units.communications.sent == []


async def test_a_test_prompt_for_an_unknown_service_or_one_with_no_reporter_is_refused() -> None:
    rig = _world()
    rig.units.people.roles.pop("role-rep-b")
    async with client(rig) as http:
        unknown = await http.post("/lead/services/svc-x/test-prompt", headers={**KEY, **LEAD_AUTH})
        nobody = await http.post("/lead/services/svc-b/test-prompt", headers={**KEY, **LEAD_AUTH})
    assert unknown.status_code == 404
    assert nobody.status_code == 409
    assert rig.units.communications.sent == []


# ------------------------------------------------------------- the lead's phoned answer (W8D)


async def test_a_lead_records_what_a_service_said_by_phone_with_no_case() -> None:
    from diucs.domain.codes import ReportSource

    rig = _world()
    async with client(rig) as http:
        response = await http.post(
            "/lead/services/svc-a/phoned",
            json={"told": "limited", "value": 3},
            headers={**KEY, **LEAD_AUTH},
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["value"] == 3
    stored = rig.units.capacity.reports["svc-a"]
    assert stored.value == 3
    assert stored.source is ReportSource.ADVISOR_PHONED
    entry = rig.units.audit.entries[-1]
    assert entry.use_case == "RecordAdvisorPhoned"
    assert entry.snapshot is not None
    assert entry.snapshot["told"] == "limited"
    assert "case_id" not in entry.snapshot


async def test_a_lead_phoned_not_accepting_stores_zero_and_takes_no_value() -> None:
    rig = _world()
    async with client(rig) as http:
        response = await http.post(
            "/lead/services/svc-a/phoned",
            json={"told": "not-accepting"},
            headers={**KEY, **LEAD_AUTH},
        )
        refused = await http.post(
            "/lead/services/svc-a/phoned",
            json={"told": "not-accepting", "value": 2},
            headers={"Idempotency-Key": "w8d-phoned-2", **LEAD_AUTH},
        )

    assert response.status_code == 201, response.text
    assert rig.units.capacity.reports["svc-a"].value == 0
    assert refused.status_code == 400


async def test_a_lead_phoned_answer_refuses_a_bad_shape_an_unknown_service_and_no_key() -> None:
    rig = _world()
    async with client(rig) as http:
        unknown_answer = await http.post(
            "/lead/services/svc-a/phoned",
            json={"told": "maybe", "value": 1},
            headers={**KEY, **LEAD_AUTH},
        )
        missing_value = await http.post(
            "/lead/services/svc-a/phoned",
            json={"told": "accepting"},
            headers={"Idempotency-Key": "w8d-phoned-3", **LEAD_AUTH},
        )
        extra_field = await http.post(
            "/lead/services/svc-a/phoned",
            json={"told": "accepting", "value": 1, "tenant": "tenant-b"},
            headers={"Idempotency-Key": "w8d-phoned-4", **LEAD_AUTH},
        )
        unknown_service = await http.post(
            "/lead/services/svc-x/phoned",
            json={"told": "accepting", "value": 1},
            headers={"Idempotency-Key": "w8d-phoned-5", **LEAD_AUTH},
        )
        no_key = await http.post(
            "/lead/services/svc-a/phoned", json={"told": "accepting", "value": 1}, headers=LEAD_AUTH
        )

    assert unknown_answer.status_code == 400
    assert missing_value.status_code == 400
    assert extra_field.status_code == 400
    assert unknown_service.status_code == 404
    assert no_key.status_code == 400
    assert rig.units.capacity.reports["svc-a"].value != 1
    assert "tenant-b" not in extra_field.text
