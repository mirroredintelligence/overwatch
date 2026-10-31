"""RecordAdvisorWorkPhone: the number a clinician phones an advisor on (W44, DEC-1034, DEC-1178).

The clinician who holds a request for advice can be shown the advisor's work phone (DEC-1034). It
is held as a protected contact under `work-<practitioner id>` (`people.work_contact_key`), the store
that already holds every role's number: this adds no store of numbers (DEC-856 item 4). The tenant
administrator writes it, for a person of their own tenant who is active; another tenant's person,
an unknown one and one who has left are the same not found. The number is never in the audit entry,
a log or the answer: the entry names the person and the kind only.

A number that is not a full UK number (eleven digits from 0, or +44) is refused and never echoed.
There is no way yet to clear a number (a known issue): a person who leaves is no longer phoned on
it because the read checks that they are active (DEC-1034).
"""

from dataclasses import dataclass
from typing import Final

from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import ScopeKind, TenantNotBound
from diucs.application.use_cases.registration_draft import is_full_uk_phone
from diucs.domain.codes import Role
from diucs.domain.errors import NotAllowed, NotFound, ValidationFailed
from diucs.domain.model.people import work_contact_key

USE_CASE: Final = "RecordAdvisorWorkPhone"
UPDATE_ACTION: Final = "U"
ALLOWED_ROLES: Final = frozenset({Role.TENANT_ADMIN})
NO_PERSON: Final = "no person with this id"


@dataclass(frozen=True, slots=True)
class RecordAdvisorWorkPhoneCommand:
    actor: Actor
    practitioner_id: str
    phone: str


def check_may_record(actor: Actor) -> None:
    if actor.role not in ALLOWED_ROLES:
        raise NotAllowed("only the tenant administrator may record an advisor's work phone")


def checked_work_phone(text: object) -> str:
    """The number without the spaces at its ends, or a refusal that does not repeat it."""
    if not isinstance(text, str) or not is_full_uk_phone(text):
        raise ValidationFailed("phone", "must be a full UK phone number")
    return text.strip()


class RecordAdvisorWorkPhone:
    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, command: RecordAdvisorWorkPhoneCommand) -> None:
        check_may_record(command.actor)
        phone = checked_work_phone(command.phone)
        async with self._uow_factory() as uow:
            scope = uow.unit_scope
            if scope is None or scope.kind is not ScopeKind.TENANT:
                raise TenantNotBound
            person = await uow.people.get_practitioner(command.practitioner_id)
            if person is None or not person.active:
                raise NotFound(NO_PERSON)
            await uow.contacts.put_phone(work_contact_key(person.id), phone)
            await uow.audit.append(
                AuditEntry(
                    action=UPDATE_ACTION,
                    use_case=USE_CASE,
                    actor=command.actor,
                    entity_ids=(person.id,),
                    snapshot={"kind": "work-phone"},
                    at=self._clock.now(),
                )
            )
            await uow.commit()
