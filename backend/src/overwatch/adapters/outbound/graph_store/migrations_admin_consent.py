"""The admin-consent invites (DEC-1316): one node per invite, unique within its tenant. Expand only.

Migration 0202 makes `(tenantId, inviteId)` unique so a racing second write of one invite is
refused instead of creating a second node. One schema statement, idempotent, fixed text.

Migration 0203 does the same for the replies the SMS webhook could not take in (DEC-1359):
`(tenantId, sid)` is unique, so a second failure of one message is the same node.
"""

from typing import Final

from overwatch.adapters.outbound.graph_store.migration_types import Migration

ADMIN_CONSENT_MIGRATIONS: Final[tuple[Migration, ...]] = (
    Migration(
        "0202_admin_consent_invites",
        statements=(
            "CREATE CONSTRAINT admin_consent_invite_id IF NOT EXISTS "
            "FOR (n:AdminConsentInvite) REQUIRE (n.tenantId, n.inviteId) IS UNIQUE",
        ),
    ),
    Migration(
        "0203_inbound_reply_failures",
        statements=(
            "CREATE CONSTRAINT inbound_reply_failure_sid IF NOT EXISTS "
            "FOR (n:InboundReplyFailure) REQUIRE (n.tenantId, n.sid) IS UNIQUE",
        ),
    ),
)
