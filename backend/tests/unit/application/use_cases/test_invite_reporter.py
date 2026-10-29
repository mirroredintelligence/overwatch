"""The pure rules of inviting a service reporter (U24): who may invite, which mobile numbers are
accepted, the pilot gate, the 48 hours, the link and the wording of the text I1.

The flow (what is stored, read back from Neo4j) is in tests/integration/application/
test_invite_reporter.py. Sample values only; no patient data.
"""

from datetime import UTC, datetime, timedelta

import pytest

from diucs.application.actor import Actor
from diucs.application.tenancy import ScopeId
from diucs.application.use_cases.invite_reporter import (
    MOBILE_MESSAGE,
    NOT_IN_PILOT_MESSAGE,
    check_in_pilot,
    check_invite_mobile,
    check_may_invite,
    command_key,
    invitation_expiry,
    invitation_link,
    lead_post,
    redacted_invitation_link,
)
from diucs.domain.codes import PractitionerRoleCode, Role, ScopeFlag
from diucs.domain.errors import NotAllowed, ValidationFailed
from diucs.domain.model.people import PractitionerRole
from tests.support.actors import ACTOR_TENANT

NOW = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)


def _actor(role: Role, practitioner_id: str | None = "prac-lead") -> Actor:
    return Actor(
        role=role,
        practitioner_id=practitioner_id,
        device_id=None,
        channel="web",
        service_ids=frozenset(),
        tenant_id=ACTOR_TENANT,
    )


def _role(
    code: PractitionerRoleCode, *, active: bool = True, role_id: str = "r-1"
) -> PractitionerRole:
    return PractitionerRole(
        id=role_id,
        practitioner_id="prac-lead",
        service_id=None,
        code=code,
        active=active,
        channel=None,
        period_start=NOW,
    )


# Who may invite.


def test_the_shift_lead_may_invite_and_the_lead_practitioner_is_returned() -> None:
    assert check_may_invite(_actor(Role.LEAD)) == "prac-lead"


@pytest.mark.parametrize("role", [role for role in Role if role is not Role.LEAD])
def test_every_other_role_is_refused(role: Role) -> None:
    with pytest.raises(NotAllowed):
        check_may_invite(_actor(role))


def test_a_lead_with_no_named_practitioner_is_refused() -> None:
    with pytest.raises(NotAllowed):
        check_may_invite(_actor(Role.LEAD, practitioner_id=None))


# The mobile number.


@pytest.mark.parametrize(
    "text",
    ["07700 900123", "07700900123", "07700-900-123", "+44 7700 900123", "+44 (0)7700 900123"],
)
def test_a_uk_mobile_is_accepted_in_any_common_form_and_returned_nationally(text: str) -> None:
    assert check_invite_mobile(text) == "07700900123"


@pytest.mark.parametrize(
    "text",
    ["0123", "", "01305 123456", "07700 90012", "07700 9001234", "07700 90012a", "+1 202 555 0100"],
)
def test_anything_that_is_not_a_uk_mobile_is_refused_with_the_screen_wording(text: str) -> None:
    with pytest.raises(ValidationFailed) as raised:
        check_invite_mobile(text)
    assert raised.value.field == "mobile"
    assert raised.value.message == MOBILE_MESSAGE
    assert MOBILE_MESSAGE == "Enter a UK mobile number, like 07700 900123"


def test_a_refused_number_is_never_echoed() -> None:
    with pytest.raises(ValidationFailed) as raised:
        check_invite_mobile("07701 777888x")
    assert "777888" not in str(raised.value)


def test_a_value_that_is_not_text_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        check_invite_mobile(7700900123)  # type: ignore[arg-type]


# The pilot gate.


def test_only_a_service_in_the_pilot_can_be_invited() -> None:
    check_in_pilot(ScopeFlag.IN_PILOT)
    for flag in (ScopeFlag.LATER, ScopeFlag.OUT_OF_SCOPE):
        with pytest.raises(NotAllowed) as raised:
            check_in_pilot(flag)
        assert str(raised.value) == NOT_IN_PILOT_MESSAGE
    assert NOT_IN_PILOT_MESSAGE == "Only services in the pilot can be invited"


# The 48 hours.


def test_an_invitation_lasts_forty_eight_hours_from_when_it_was_sent() -> None:
    assert invitation_expiry(NOW) == NOW + timedelta(hours=48)
    assert invitation_expiry(NOW) == datetime(2026, 10, 31, 9, 0, tzinfo=UTC)


def test_a_naive_send_time_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        invitation_expiry(datetime(2026, 10, 29, 9, 0))


# The link and the key.


def test_the_link_is_the_tenant_host_the_invitation_path_and_the_token() -> None:
    assert invitation_link("https://diucs.example", "abc123") == "https://diucs.example/i/abc123"


def test_a_trailing_slash_on_the_host_makes_no_difference() -> None:
    assert invitation_link("https://diucs.example/", "abc123") == "https://diucs.example/i/abc123"


def test_the_stored_copy_of_the_link_holds_no_token() -> None:
    assert redacted_invitation_link("https://diucs.example") == "https://diucs.example/i/[link]"


def test_the_replay_key_names_the_operation_and_the_tenant() -> None:
    key = command_key("invite", ScopeId.tenant("tenant-a"), "k-1")
    assert key == "invite-reporter:invite:tenant-a:k-1"
    assert key != command_key("invite", ScopeId.tenant("tenant-b"), "k-1")
    assert key != command_key("resend", ScopeId.tenant("tenant-a"), "k-1")


# The lead's post.


def test_the_lead_post_is_the_active_shift_lead_role() -> None:
    roles = [
        _role(PractitionerRoleCode.CLINICAL_LEAD, role_id="r-clinical"),
        _role(PractitionerRoleCode.SHIFT_LEAD, role_id="r-lead"),
    ]
    found = lead_post(roles)
    assert found is not None
    assert found.id == "r-lead"


def test_an_inactive_shift_lead_role_is_not_a_post_and_none_is_none() -> None:
    assert lead_post([_role(PractitionerRoleCode.SHIFT_LEAD, active=False)]) is None
    assert lead_post([]) is None


def test_when_several_shift_lead_roles_exist_the_lowest_id_is_chosen() -> None:
    roles = [
        _role(PractitionerRoleCode.SHIFT_LEAD, role_id="r-b"),
        _role(PractitionerRoleCode.SHIFT_LEAD, role_id="r-a"),
    ]
    found = lead_post(roles)
    assert found is not None
    assert found.id == "r-a"
