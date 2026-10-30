"""A test push to the reporter's own phone (W7C, DEC-824).

The All-set page of set-up sends one so the reporter sees that notifications work before they rely
on them. It is queued like every message (the sealed send of DEC-116) to the reporter's own post,
and the push sender delivers it to every installed app of the person. It says nothing about a
service, a figure or a person and carries no link. A reporter with no saved subscription gets
`NoPushSubscription`, so the page can say the save did not happen instead of a test that never
arrives.
"""

from typing import Final

from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.sealing import ContentSealer
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.sealed_send import queue_message
from diucs.application.tenancy import ScopeKind, TenantNotBound
from diucs.application.use_cases.reporter_app import held_services
from diucs.domain.codes import Channel
from diucs.domain.errors import DomainError, NotFound
from diucs.domain.messages.catalogue import MessageId
from diucs.domain.messages.templates import render

TEST_TITLE: Final = "Test notification"
TEST_BODY: Final = "Capacity notifications are working on this phone."
USE_CASE: Final = "SendPushTest"


class NoPushSubscription(DomainError):
    """The reporter has no saved push subscription to send a test to."""


class SendPushTest:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        ids: IdGenerator,
        sealer: ContentSealer,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids
        self._sealer = sealer

    async def execute(self, actor: Actor) -> str:
        """Queue the test and return its communication id."""
        now = self._clock.now()
        async with self._uow_factory() as uow:
            scope = uow.unit_scope
            if scope is None or scope.kind is not ScopeKind.TENANT:
                raise TenantNotBound
            held = await held_services(uow, actor, now)
            if not held.own:
                raise NotFound("no post")
            role = min(held.own, key=lambda own: (held.names.get(own.service_id or "", ""), own.id))
            if not await uow.push_subscriptions.for_practitioner(held.practitioner.id):
                raise NoPushSubscription
            communication_id = await queue_message(
                uow,
                self._ids,
                self._sealer,
                scope=scope,
                rendered=render(MessageId.K3, Channel.PUSH, title=TEST_TITLE, body=TEST_BODY),
                recipient_role_id=role.id,
                about_id=role.service_id,
                now=now,
            )
            await uow.audit.append(
                AuditEntry(
                    action="C",
                    use_case=USE_CASE,
                    actor=actor,
                    entity_ids=(communication_id, role.id),
                    snapshot={"channel": Channel.PUSH.value},
                    at=now,
                )
            )
            await uow.commit()
        return communication_id
