"""The wording of the admin-consent invitation email (DEC-1316 item 3).

FOR OWNER REVIEW: the wording below is the first draft and is the owner's to approve. It names the
organisation, says it is from Overwatch, says in plain English what the consent allows and that it
allows nothing else, gives the link, and says to ignore it if it is unexpected. It holds no patient
data and no token other than the link.
"""

from dataclasses import dataclass
from typing import Final

SUBJECT_TEMPLATE: Final = "Overwatch: please approve access for {organisation}"

BODY_TEMPLATE: Final = """Hello,

This message is from Overwatch, the urgent-care capacity service. {organisation} is being set up on
Overwatch, and you have been named as the person who administers {organisation}'s Microsoft Entra
directory (the account system your staff sign in with).

To let your staff sign in to Overwatch with their work accounts, please approve Overwatch in your
Entra directory. If you approve, Overwatch will be able to:

  - read and manage the groups whose names start with {ods}_overwatch_ , and their members;
  - read users, so that it can add the right people to those groups.

It will not be able to do anything else in your directory.

To review and approve, open this link and sign in with your administrator account:

{link}

The link works for 7 days. If you were not expecting this message, please ignore it: nothing will
change unless you open the link and approve.

Overwatch
"""


@dataclass(frozen=True, slots=True)
class InvitationEmail:
    subject: str
    text: str


def render_invitation(*, organisation: str, ods: str, link: str) -> InvitationEmail:
    """The subject and text. `organisation` is the tenant's display name, `ods` the prefix of the
    groups (the ODS code, or the tenant id when the organisation has none)."""
    return InvitationEmail(
        subject=SUBJECT_TEMPLATE.format(organisation=organisation),
        text=BODY_TEMPLATE.format(organisation=organisation, ods=ods, link=link),
    )
