"""The access log hides an invitation token as it hides a link token (W7C, H-450): an invitation is
read at `/invitations/<token>` and its code is asked for and checked at
`/identity/invitations/<token>/code`. Synthetic values only."""

import logging

import pytest

from diucs.adapters.inbound.link_pages.capacity_links import RedactLinkTokens

TOKEN = "AbCdEfGhIjKlMnOpQrStUvW"


def _record(msg: str, *args: object) -> logging.LogRecord:
    return logging.LogRecord("uvicorn.access", logging.INFO, "x", 1, msg, args or None, None)


@pytest.mark.parametrize(
    ("path", "shown"),
    [
        (f"/invitations/{TOKEN}", "/invitations/[token]"),
        (f"/identity/invitations/{TOKEN}/code", "/identity/invitations/[token]/code"),
        (
            f"/identity/invitations/{TOKEN}/code/verify",
            "/identity/invitations/[token]/code/verify",
        ),
        (
            f"https://alpha.example.org/invitations/{TOKEN}?a=1",
            "https://alpha.example.org/invitations/[token]?a=1",
        ),
        ("/invitations/", "/invitations/"),
        (f"/links/{TOKEN}", "/links/[token]"),
        ("/identity/code", "/identity/code"),
    ],
)
def test_the_token_of_an_invitation_path_is_hidden(path: str, shown: str) -> None:
    record = _record("%s", path)

    assert RedactLinkTokens().filter(record) is True

    assert record.getMessage() == shown
    assert TOKEN not in record.getMessage()
