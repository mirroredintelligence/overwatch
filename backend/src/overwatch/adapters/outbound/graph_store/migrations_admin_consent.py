"""The admin-consent invites (DEC-1316): one node per invite, unique within its tenant. Expand only.

Migration 0202 makes `(tenantId, inviteId)` unique so a racing second write of one invite is
refused instead of creating a second node. One schema statement, idempotent, fixed text.
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
)
