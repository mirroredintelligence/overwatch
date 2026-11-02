"""The admin-consent invitation email (DEC-1316 item 3, DEC-1317): a branded HTML message and a
plain-text fallback with the same words.

FOR OWNER REVIEW: the wording is a draft and is the owner's to approve. It names the organisation,
says it is from Overwatch, says in plain English what approving allows (the Graph permissions of
DEC-1317) and what it does not, gives the link, and says to ignore the message if unexpected. It
holds no patient data and no token other than the link.

The HTML is table-based with inline styles, because mail apps ignore most CSS: one 600 px card on a
light page, the Overwatch wordmark as a PNG (mail apps do not show SVG), one button, and the link
spelled out under it. Every value that goes into it is escaped.
"""

from dataclasses import dataclass
from html import escape
from typing import Final
from urllib.parse import urlsplit

SUBJECT_TEMPLATE: Final = "Overwatch: please approve access for {organisation}"
LOGO_PATH: Final = "/brand/overwatch-logo-email.png"
LINK_DAYS: Final = 7

_INK: Final = "#14232B"
_MUTED: Final = "#44555D"
_BLUE: Final = "#0B5C8C"
_PAGE: Final = "#F4F6F5"
_EDGE: Final = "#DDE3E6"
_FONT: Final = "Arial, Helvetica, sans-serif"

TEXT_TEMPLATE: Final = """Hello,

This message is from Overwatch, the urgent-care capacity service. {organisation} is being set up
on Overwatch, and you have been named as the person who looks after {organisation}'s Microsoft
work accounts (Microsoft Entra).

To let your staff sign in to Overwatch with their work accounts, please approve Overwatch in your
Microsoft Entra directory. Approving lets Overwatch:

  - create teams (groups) for {organisation} whose names start with {ods}_overwatch_ , and add
    and remove the people in them;
  - look people up by email address, so it can add the right people;
  - give those teams access to Overwatch.

Overwatch does not read anyone's email or files. Microsoft's permission is wider than the way
Overwatch uses it, so Overwatch's own rules keep it to teams whose names start with
{ods}_overwatch_ . You can review or remove Overwatch's access at any time in Microsoft Entra,
under Enterprise applications.

To review and approve, open this link and sign in with your administrator account:

{link}

The link works for {days} days. If you were not expecting this message, please ignore it: nothing
will change unless you open the link and approve.

Overwatch
"""


@dataclass(frozen=True, slots=True)
class InvitationEmail:
    subject: str
    text: str
    html: str


def logo_url_for(redirect_uri: str) -> str:
    """The wordmark's address: on the same web address the consent link returns to."""
    parts = urlsplit(redirect_uri)
    return f"{parts.scheme}://{parts.netloc}{LOGO_PATH}"


def _paragraph(text: str, *, muted: bool = False) -> str:
    colour = _MUTED if muted else _INK
    return (
        f'<p style="margin:0 0 16px 0;font-family:{_FONT};font-size:17px;line-height:26px;'
        f'color:{colour};">{text}</p>'
    )


def _bullets(items: list[str]) -> str:
    rows = "".join(f'<li style="margin:0 0 8px 0;padding:0;">{item}</li>' for item in items)
    return (
        f'<ul style="margin:0 0 16px 0;padding:0 0 0 22px;font-family:{_FONT};font-size:17px;'
        f'line-height:26px;color:{_INK};">{rows}</ul>'
    )


def _button(href: str) -> str:
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="margin:8px 0;">'
        f'<tr><td align="center" bgcolor="{_BLUE}" style="border-radius:10px;">'
        f'<a href="{href}" style="display:inline-block;padding:16px 28px;font-family:{_FONT};'
        "font-size:18px;font-weight:700;line-height:22px;color:#FFFFFF;text-decoration:none;"
        f'border-radius:10px;background:{_BLUE};">Review and approve</a>'
        "</td></tr></table>"
    )


def render_html(*, organisation: str, ods: str, link: str, logo_url: str) -> str:
    org = escape(organisation)
    prefix = escape(f"{ods}_overwatch_")
    href = escape(link, quote=True)
    logo = escape(logo_url, quote=True)
    allows = _bullets(
        [
            f"create teams (groups) for {org} whose names start with <strong>{prefix}</strong>, "
            "and add and remove the people in them;",
            "look people up by email address, so it can add the right people;",
            "give those teams access to Overwatch.",
        ]
    )
    intro = _paragraph(
        f"Hello, {org} is being set up on Overwatch, the urgent-care capacity service. You have "
        f"been named as the person who looks after {org}&rsquo;s Microsoft work accounts "
        "(Microsoft Entra)."
    ) + _paragraph(
        "To let your staff sign in to Overwatch with their work accounts, please approve "
        "Overwatch in your Microsoft Entra directory. Approving lets Overwatch:"
    )
    reassurance = _paragraph(
        "Overwatch does not read anyone&rsquo;s email or files. Microsoft&rsquo;s permission is "
        "wider than the way Overwatch uses it, so Overwatch&rsquo;s own rules keep it to teams "
        f"whose names start with <strong>{prefix}</strong>. You can review or remove "
        "Overwatch&rsquo;s access at any time in Microsoft Entra, under Enterprise applications.",
        muted=True,
    ) + _paragraph(
        "If the button does not work, copy this address into your browser:<br>"
        f'<a href="{href}" style="color:{_BLUE};word-break:break-all;">{escape(link)}</a>',
        muted=True,
    )
    footer = _paragraph(
        f"The link works for {LINK_DAYS} days. If you were not expecting this message, please "
        "ignore it: nothing will change unless you open the link and approve.",
        muted=True,
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="color-scheme" content="light">'
        '<meta name="supported-color-schemes" content="light">'
        f"<title>Approve Overwatch for {org}</title></head>"
        f'<body style="margin:0;padding:0;background:{_PAGE};">'
        '<div style="display:none;max-height:0;overflow:hidden;opacity:0;">'
        f"Approve Overwatch so {org}&rsquo;s staff can sign in with their work accounts.</div>"
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'bgcolor="{_PAGE}"><tr><td align="center" style="padding:32px 12px;">'
        '<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" '
        f'style="width:100%;max-width:600px;background:#FFFFFF;border:1px solid {_EDGE};'
        'border-radius:16px;">'
        '<tr><td style="padding:28px 32px 0 32px;">'
        f'<img src="{logo}" width="208" height="48" alt="Overwatch" '
        'style="display:block;border:0;outline:none;height:48px;width:208px;"></td></tr>'
        '<tr><td style="padding:24px 32px 8px 32px;">'
        f'<h1 style="margin:0 0 16px 0;font-family:{_FONT};font-size:26px;line-height:32px;'
        f'color:{_INK};">Approve Overwatch for {org}</h1>'
        f"{intro}{allows}</td></tr>"
        f'<tr><td style="padding:0 32px 8px 32px;">{_button(href)}</td></tr>'
        f'<tr><td style="padding:16px 32px 8px 32px;">{reassurance}</td></tr>'
        f'<tr><td style="padding:8px 32px 28px 32px;border-top:1px solid {_EDGE};">{footer}'
        f'<p style="margin:0;font-family:{_FONT};font-size:15px;line-height:22px;'
        f'color:{_MUTED};">Overwatch</p></td></tr></table></td></tr></table></body></html>'
    )


def render_invitation(*, organisation: str, ods: str, link: str, logo_url: str) -> InvitationEmail:
    """The subject, the plain text and the HTML. `organisation` is the tenant's display name, `ods`
    the prefix of the groups (the ODS code, or the tenant id when the organisation has none)."""
    return InvitationEmail(
        subject=SUBJECT_TEMPLATE.format(organisation=organisation),
        text=TEXT_TEMPLATE.format(organisation=organisation, ods=ods, link=link, days=LINK_DAYS),
        html=render_html(organisation=organisation, ods=ods, link=link, logo_url=logo_url),
    )
