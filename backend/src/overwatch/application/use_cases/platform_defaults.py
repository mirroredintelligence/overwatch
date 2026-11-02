"""The platform's standard settings, applied when a tenant is made (DEC-1322).

A new tenant starts with the platform's defaults for everything that has one, so its administrators
change what they need to and are not asked to accept each default by hand:

- the data-retention schedule (`default_retention`, each class one stored rule);
- the settings. Every clinical and operational setting has a default of its own, so the first
  version holds no override of them. The one thing with no default, the words a message may
  print, is given the platform's names, and that makes version 1 (approved on the platform's
  behalf).

Applying it twice changes nothing: retention is written only when none is stored, and the settings
version only when no version is in force. A tenant that has moved on (a version in force, retention
stored) is left exactly as it is. What stays with the organisation: its contacts, its numbers, its
directory and the districts of its area, which have no sensible default.
"""

from typing import Final

from overwatch.application.ports.outbound.clock import Clock
from overwatch.application.ports.outbound.unit_of_work import UnitOfWork
from overwatch.application.use_cases.tenant_config import apply_approval, plan_moves
from overwatch.domain.model.tenant import ConfigStatus, TenantConfig
from overwatch.domain.model.tenant_records import default_retention

PLATFORM_DEFAULTS_REF: Final = "platform-defaults"
"""The author and approver of the first version: the platform, not a person."""
DEFAULT_WORDING: Final = {
    "systemName": "Overwatch",
    "referralSystemName": "Overwatch",
    "coordinationTeamName": "coordination team",
}


async def apply_platform_defaults(uow: UnitOfWork, clock: Clock) -> dict[str, object]:
    """Write what is missing, inside the caller's unit of work and bound tenant (the caller
    commits). Returns what was done, for the caller's audit entry."""
    repo = uow.tenant_config
    done: dict[str, object] = {"retention": False, "settingsVersion": None}
    if not await repo.retention():
        for rule in default_retention():
            await repo.put_retention(rule)
        done["retention"] = True
    if await repo.current_version() is None:
        now = clock.now()
        draft = TenantConfig(
            version=await repo.latest_version_number() + 1,
            status=ConfigStatus.DRAFT,
            values=DEFAULT_WORDING,
            created_at=now,
            created_by_ref=PLATFORM_DEFAULTS_REF,
        )
        await repo.add_version(draft)
        approved = apply_approval(draft, None, PLATFORM_DEFAULTS_REF, now)
        for version, expected in plan_moves(draft, approved):
            await repo.move_version(version, expected)
        done["settingsVersion"] = approved.version
    return done
