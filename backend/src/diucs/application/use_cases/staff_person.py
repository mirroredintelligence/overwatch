"""The person record of a signed-in executive (W9H, DEC-1042).

An executive signs in through the organisation's directory, and the token's subject is a derived
staff subject (`stf-` and hex), so no Practitioner exists for them. A push subscription is stored
against a Practitioner, so the first time an executive saves one this makes the minimal record: the
subject as the id, active, a fixed display name that is no one's name, and no phone. It is not a
reporter (no post, no number, no device) and nothing finds it by a phone. A record that already
exists is left exactly as it is, so a person who was removed is not brought back by signing in
again: the next check of the person (`CheckReporterAccess`) refuses them.

Only the executive role: another role's person is not made here.
"""

from typing import Final

from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import ScopeKind, TenantNotBound
from diucs.domain.codes import Role
from diucs.domain.errors import Conflict, NotAllowed
from diucs.domain.model.people import Practitioner

STAFF_PERSON_ROLES: Final = frozenset({Role.EXEC})
STAFF_DISPLAY_NAME: Final = "Executive"
"""What the record is called: a word, never a person's name (a directory name is not copied)."""
USE_CASE: Final = "EnsureStaffPerson"


class EnsureStaffPerson:
    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, actor: Actor) -> None:
        if actor.role not in STAFF_PERSON_ROLES or actor.practitioner_id is None:
            raise NotAllowed("no person record is made for this role")
        person_id = actor.practitioner_id
        async with self._uow_factory() as uow:
            scope = uow.unit_scope
            if scope is None or scope.kind is not ScopeKind.TENANT:
                raise TenantNotBound
            if await uow.people.get_practitioner(person_id) is not None:
                return
            try:
                await uow.people.save_practitioner(
                    Practitioner(
                        id=person_id, active=True, display_name=STAFF_DISPLAY_NAME, phone_hash=None
                    )
                )
            except Conflict:
                # Two first saves at once: the other made it, which is all this was for.
                return
            await uow.audit.append(
                AuditEntry(
                    action="C",
                    use_case=USE_CASE,
                    actor=actor,
                    entity_ids=(person_id,),
                    snapshot={"role": actor.role.value},
                    at=self._clock.now(),
                )
            )
            await uow.commit()
