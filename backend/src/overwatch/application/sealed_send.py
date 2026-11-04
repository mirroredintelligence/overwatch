"""Queue one outbound message to a recipient role, the way the senders (I10) read it (DEC-116).

A use case writes the Communication (its text with any link replaced by the placeholder, so no
token is at rest) and one SendMessage outbox message whose content is sealed under the outbox
message id, the bound tenant and the recipient role. The senders open it at send time and send
through the tenant's own sender. A use case never sends anything itself.
"""

import json
from datetime import datetime
from typing import Final

from overwatch.application.ports.outbound.ids import IdGenerator
from overwatch.application.ports.outbound.messaging import Communication
from overwatch.application.ports.outbound.outbox import OutboxMessage
from overwatch.application.ports.outbound.sealing import ContentSealer
from overwatch.application.ports.outbound.unit_of_work import UnitOfWork
from overwatch.application.tenancy import ScopeId, ScopeKind, TenantNotBound
from overwatch.application.use_cases.send_prompts import LINK_PLACEHOLDER
from overwatch.domain.messages.templates import RenderedMessage

MESSAGES_TOPIC: Final = "messages.outbound"
SEND_MESSAGE: Final = "SendMessage"


async def queue_message(
    uow: UnitOfWork,
    ids: IdGenerator,
    sealer: ContentSealer,
    *,
    scope: ScopeId,
    rendered: RenderedMessage,
    recipient_role_id: str,
    about_id: str | None,
    now: datetime,
    link: str | None = None,
) -> str:
    """Write the Communication and its SendMessage in the caller's unit of work, and return the
    communication id. `link` is the URL inside the text, if any: it is stored as the placeholder."""
    communication_id = ids.new_id()
    outbox_id = ids.new_id()
    content = json.dumps(
        {"text": rendered.text, "subject": rendered.subject, "html": rendered.html},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    sealed = sealer.seal(
        content,
        message_id=outbox_id,
        tenant_id=scope.value,
        recipient_role_id=recipient_role_id,
    )
    stored_text = rendered.text if link is None else rendered.text.replace(link, LINK_PLACEHOLDER)
    await uow.communications.add(
        Communication(
            id=communication_id,
            message_id=rendered.message_id.value,
            channel=rendered.channel,
            recipient_role_id=recipient_role_id,
            about_id=about_id,
            payload_text=stored_text,
            sent_at=now,
            delivery_status="queued",
        )
    )
    await uow.outbox.add(
        OutboxMessage(
            id=outbox_id,
            topic=MESSAGES_TOPIC,
            event_type=SEND_MESSAGE,
            payload={
                "communication_id": communication_id,
                "message_id": rendered.message_id.value,
                "channel": rendered.channel.value,
                "recipient_role_id": recipient_role_id,
                "sealed_content": sealed,
            },
            created_at=now,
        )
    )
    return communication_id


def seal_outbound_text(
    sealer: ContentSealer,
    *,
    outbox_id: str,
    tenant_id: str,
    recipient_role_id: str,
    text: str,
    subject: str | None = None,
    html: str | None = None,
) -> str:
    """The sealed content of a message written outside the rendering path (an echo, an invitation).
    The sender refuses a payload that carries its text in the clear (DEC-1336), so every such write
    seals here, bound to its outbox message, tenant and recipient."""
    content = json.dumps(
        {"text": text, "subject": subject, "html": html},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return sealer.seal(
        content, message_id=outbox_id, tenant_id=tenant_id, recipient_role_id=recipient_role_id
    )


def tenant_of(unit_scope: ScopeId | None) -> str:
    """The tenant an outbound text is sealed for: the unit of work's own tenant scope."""
    if unit_scope is None or unit_scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return unit_scope.value
