"""The wording of the invitation email (DEC-1316 item 3). The wording is for owner review, so these
tests pin what it must say and must not say, not every word."""

from overwatch.application.admin_consent_email import (
    BODY_TEMPLATE,
    SUBJECT_TEMPLATE,
    render_invitation,
)

LINK = "https://login.microsoftonline.com/0f5a7c1e-3b2d-4c6a-9e8f-1a2b3c4d5e6f/adminconsent?state=x"


def _text() -> str:
    return render_invitation(organisation="The Ardleigh Surgery", ods="F81044", link=LINK).text


def test_it_names_the_organisation_and_says_it_is_from_overwatch() -> None:
    message = render_invitation(organisation="The Ardleigh Surgery", ods="F81044", link=LINK)
    assert "The Ardleigh Surgery" in message.subject
    assert "Overwatch" in message.subject
    assert "This message is from Overwatch" in message.text
    assert "The Ardleigh Surgery" in message.text


def test_it_says_what_the_consent_grants_and_that_it_grants_nothing_else() -> None:
    text = _text()
    assert "F81044_overwatch_" in text
    assert "read and manage the groups" in text and "their members" in text
    assert "read users" in text
    assert "It will not be able to do anything else" in text


def test_it_gives_the_link_once_and_says_to_ignore_it_if_unexpected() -> None:
    text = _text()
    assert text.count(LINK) == 1
    assert "were not expecting this message, please ignore it" in text
    assert "7 days" in text


def test_it_holds_no_html_placeholder_left_over_and_no_patient_words() -> None:
    text = _text()
    assert "{" not in text and "}" not in text
    for word in ("patient", "NHS number", "postcode"):
        assert word not in text.lower()


def test_the_templates_are_constants_with_exactly_these_fields() -> None:
    assert "{organisation}" in SUBJECT_TEMPLATE
    for field in ("{organisation}", "{ods}", "{link}"):
        assert field in BODY_TEMPLATE
