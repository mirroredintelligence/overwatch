"""The invitation email (DEC-1316 item 3, DEC-1317). The wording is for owner review, so these tests
pin what it must say and must not say, and that the HTML is safe and complete, not every word."""

from overwatch.application.admin_consent_email import (
    SUBJECT_TEMPLATE,
    TEXT_TEMPLATE,
    logo_url_for,
    render_invitation,
)

LINK = "https://login.microsoftonline.com/0f5a7c1e-3b2d-4c6a-9e8f-1a2b3c4d5e6f/adminconsent?state=x&y=1"
LOGO = "https://overwatch.example/brand/overwatch-logo-email.png"
ORG = "The Ardleigh Surgery"


def _message(organisation: str = ORG, ods: str = "F81044"):  # type: ignore[no-untyped-def]
    return render_invitation(organisation=organisation, ods=ods, link=LINK, logo_url=LOGO)


def test_it_names_the_organisation_and_says_it_is_from_overwatch() -> None:
    message = _message()
    assert ORG in message.subject and "Overwatch" in message.subject
    assert "This message is from Overwatch" in message.text
    assert ORG in message.text and ORG in message.html


def test_it_says_what_approving_allows_and_what_it_does_not() -> None:
    for raw in (_message().text, _message().html):
        body = " ".join(raw.split())  # the text version wraps its lines
        assert "F81044_overwatch_" in body
        assert "look people up by email address" in body
        assert "give those teams access to Overwatch" in body
        assert "does not read anyone" in body
        assert "wider than the way Overwatch uses it" in body


def test_it_gives_the_link_and_says_to_ignore_it_if_unexpected() -> None:
    message = _message()
    assert message.text.count(LINK) == 1
    assert "were not expecting this message, please ignore it" in message.text
    assert "7 days" in message.text and "7 days" in message.html
    assert "ignore it" in message.html


def test_the_html_is_a_branded_card_with_one_button_and_the_logo() -> None:
    html = _message().html
    assert html.startswith("<!doctype html>")
    assert f'src="{LOGO}"' in html and 'alt="Overwatch"' in html
    assert html.count("Review and approve") == 1
    assert 'href="https://login.microsoftonline.com/' in html
    assert "<table" in html and "max-width:600px" in html


def test_every_value_in_the_html_is_escaped() -> None:
    html = _message(organisation='<script>alert("x")</script> & Co', ods="A<B").html
    assert "<script>" not in html
    assert "&lt;script&gt;" in html and "&amp; Co" in html
    assert "A&lt;B_overwatch_" in html
    # The link is escaped for an attribute, so its ampersand and quote cannot break out.
    assert "state=x&amp;y=1" in html


def test_the_logo_is_on_the_web_address_the_consent_link_returns_to() -> None:
    redirect = "https://overwatch.mirroredintelligence.com/admin-consent/return"
    assert logo_url_for(redirect) == (
        "https://overwatch.mirroredintelligence.com/brand/overwatch-logo-email.png"
    )


def test_it_holds_no_placeholder_left_over_and_no_patient_words() -> None:
    message = _message()
    for body in (message.text, message.html):
        assert "{organisation}" not in body and "{ods}" not in body and "{link}" not in body
        for word in ("patient", "NHS number", "postcode"):
            assert word not in body.lower()


def test_the_templates_are_constants_with_exactly_these_fields() -> None:
    assert "{organisation}" in SUBJECT_TEMPLATE
    for field in ("{organisation}", "{ods}", "{link}", "{days}"):
        assert field in TEXT_TEMPLATE
