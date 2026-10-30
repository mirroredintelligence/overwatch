"""A rig for the link tests (L01): UCR West, its reporter, a figure on record, a real prompt sent by
SendPrompts (so the link under test is the one a reporter is texted), and the three link use
cases, all on one clock and one cache.

Friday 23 October 2026 is in British Summer Time, so a London wall time is one hour ahead of UTC.
The service reports every 2 hours between 08:00 and 20:00. The figure on record is 3, as of 08:15
(07:15 UTC); the prompt goes out at 10:00 and closes at 10:30. Synthetic values only: no patient
data, no real phone number. The host names are made up.
"""

import functools
import hashlib
import hmac
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.content_seal.aes_gcm import AesGcmContentSealer
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.application.actor import Actor
from diucs.application.ports.outbound.outbox import OutboxMessage
from diucs.application.ports.outbound.tokens import (
    LINK_TOKEN_SECRET,
    LinkTokenRepository,
    LinkTokenService,
)
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.confirm_capacity import ConfirmCapacity, ConfirmCapacityCommand
from diucs.application.use_cases.link_access import (
    CAPACITY_PURPOSE,
    LINK_CSRF_SECRET,
    LINK_PROMPT_MESSAGES,
    CapacityLinkHandler,
    LinkPurposes,
    RenewLink,
    RenewLinkCommand,
    RespondViaLink,
    RespondViaLinkCommand,
    UnitOfWorkIdempotency,
    ViewLink,
    ViewLinkQuery,
)
from diucs.application.use_cases.link_access import LinkAction as LinkAction
from diucs.application.use_cases.report_capacity import ReportCapacity
from diucs.domain.codes import ReportSource, Role
from diucs.domain.model.service import ServiceProfile
from diucs.domain.rules.schedule import reply_by
from diucs.domain.rules.tokens import hash_token
from tests.support.actors import ACTOR_TENANT
from tests.support.ladder_rig import (
    LINK_BASE,
    PHONE_HASH_1,
    SECRET,
    Rig,
    build_rig,
    london,
    reporter,
    seed_people,
    seed_report,
    virtual_ward,
)
from tests.support.neo4j import read_tx
from tests.support.tenancy import as_tenant, run_host
from tests.support.uow import ensure_audit_heads

CSRF_SECRET = b"link-csrf-secret-for-the-link-tests"
SERVICE_ID = "ucr-west"
SERVICE_NAME = "UCR West"
UNIT_LABEL = "referrals in the next 2 hrs"
HOST_A = run_host("alpha")
HOST_B = run_host("bravo")
BASE_URL_A = f"https://{HOST_A}/l"
CLIENT = "198.51.100.7"
OTHER_CLIENT = "198.51.100.8"
FIGURE_AT = london(8, 15)
PROMPT_AT = london(10, 0)
ANSWER_AT = london(10, 5)
REPLY_BY = london(10, 30)
NEXT_DUE = london(12, 0)
SEALED_TOKEN = re.compile(rf"{re.escape(LINK_BASE)}/([A-Za-z]+)")


def new_secrets() -> FixedSecretStore:
    return FixedSecretStore({LINK_TOKEN_SECRET: SECRET, LINK_CSRF_SECRET: CSRF_SECRET})


def ucr_west(service_id: str = SERVICE_ID, **changes: Any) -> ServiceProfile:
    return virtual_ward(service_id, **{"name": SERVICE_NAME, "unit_label": UNIT_LABEL, **changes})


def token_hash_of(token: str) -> str:
    """The stored hash of a token, computed here and not by the code under test."""
    return hash_token(token, SECRET)


def _in_own_tenant[**P, R](method: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Run a rig method with the rig's own tenant bound, as the edge would bind it for a request.
    The tests of the link pages run with no tenant bound, so that the route must bind one from the
    host; the rig's reads and its direct use-case calls are the test's own work and bind here."""

    @functools.wraps(method)
    async def bound(self: Any, *args: P.args, **kwargs: P.kwargs) -> R:
        with as_tenant(self.tenant):
            return await method(self, *args, **kwargs)

    return bound


@dataclass(slots=True)
class LinkRig:
    factory: UnitOfWorkFactory
    driver: AsyncDriver
    tenant: str
    clock: FixedClock
    cache: InMemoryCache
    secrets: FixedSecretStore
    sealer: AesGcmContentSealer
    ids: SequentialIds
    rig: Rig
    purposes: LinkPurposes
    view_link: ViewLink
    respond_link: RespondViaLink
    renew_link: RenewLink
    service_id: str
    prefix: str
    phone: str

    # -- seeding -------------------------------------------------------------------------

    @_in_own_tenant
    async def seed(
        self,
        *,
        figure: int | None = 3,
        figure_at: datetime = FIGURE_AT,
        profile: ServiceProfile | None = None,
        reporters: int = 1,
    ) -> None:
        """The service, its reporter(s) and the figure on record, committed."""
        await ensure_audit_heads(self.driver, self.tenant)
        service = profile or ucr_west(self.service_id)
        async with self.factory() as uow:
            await uow.services.save(service)
            await uow.commit()
        await seed_people(
            self.factory,
            *[
                reporter(
                    number,
                    self.phone if number == 1 else f"{number:02x}" * 32,
                    service.id,
                    self.prefix,
                )
                for number in range(1, reporters + 1)
            ],
        )
        if figure is not None:
            # The store stamps a write with the clock of the unit of work, so the figure is written
            # at its own time: a report written after the prompt would count as "since" (H-32).
            self.clock.set(figure_at)
            await seed_report(
                self.factory,
                figure_at,
                service_id=service.id,
                report_id=f"{self.prefix}seed-report-1",
                value=figure,
            )

    @_in_own_tenant
    async def prompt(self, at: datetime = PROMPT_AT) -> str:
        """Send the prompt due at `at` and return the token of its link, read from the text the
        reporter is sent (opened as the sender opens it). The clock is left at `at`."""
        await self.rig.prompt(at)
        text = ""
        for message in await self.rig.events("SendMessage"):
            if message.payload["recipient_role_id"] == f"{self.prefix}role-1":
                text = str(self.rig.opened(message)["text"])
        found = SEALED_TOKEN.search(text)
        if found is not None:
            return found.group(1)
        # C2 over text (a service with no figure) carries no link: U03 still stores the token, and
        # the only way to hold it is to issue one for that prompt here.
        async with self.factory() as uow:
            prompt = await uow.communications.latest_prompt_for_phone(
                {f"{self.prefix}role-1"}, LINK_PROMPT_MESSAGES
            )
        assert prompt is not None, "no prompt was sent"
        return await self.issue(about_id=prompt.id, expires_at=reply_by(at))

    @_in_own_tenant
    async def issue(
        self,
        *,
        about_id: str,
        phone_hash: str | None = "",
        expires_at: datetime = REPLY_BY,
        purpose: str = CAPACITY_PURPOSE,
    ) -> str:
        """A token of any shape, written straight to the store (for the cases a real prompt cannot
        make: no phone, a prompt that is not there, another purpose)."""
        async with self.factory() as uow:
            service = LinkTokenService(uow.link_tokens, self.secrets, self.clock)
            token = await service.issue(
                purpose, about_id, self.phone if phone_hash == "" else phone_hash, expires_at
            )
            await uow.commit()
        return token

    # -- the use cases, as a client calls them ---------------------------------------------

    @_in_own_tenant
    async def view(self, token: str, client: str = CLIENT) -> Any:
        return await self.view_link.execute(ViewLinkQuery(token=token, client=client))

    def csrf(self, token: str) -> str:
        """The CSRF token of a link, computed here with hmac and not by the code under test."""
        return hmac.new(
            CSRF_SECRET, token_hash_of(token).encode("ascii"), hashlib.sha256
        ).hexdigest()

    @_in_own_tenant
    async def respond(
        self,
        token: str,
        action: str = "confirm",
        value: int | None = None,
        *,
        out_of_range: bool = False,
        csrf: str | None = "",
        client: str = CLIENT,
    ) -> Any:
        """`csrf=""` means the right CSRF token for this link; None sends none."""
        return await self.respond_link.execute(
            RespondViaLinkCommand(
                token=token,
                csrf_token=self.csrf(token) if csrf == "" else csrf,
                action=LinkAction(action, value, out_of_range),
                client=client,
            )
        )

    @_in_own_tenant
    async def text_confirm(self, key: str, at: datetime) -> Any:
        """A Y by text for the service, at `at` (ConfirmCapacity as the reply handler calls it)."""
        self.clock.set(at)
        confirms = ConfirmCapacity(
            self.factory, self.clock, self.ids, UnitOfWorkIdempotency(self.factory)
        )
        return await confirms.execute(
            ConfirmCapacityCommand(
                idempotency_key=key,
                actor=Actor(
                    role=Role.REPORTER,
                    practitioner_id=f"{self.prefix}prac-1",
                    device_id=None,
                    channel="text",
                    service_ids=frozenset({self.service_id}),
                    tenant_id=ACTOR_TENANT,
                ),
                service_id=self.service_id,
                source=ReportSource.TEXT,
                performer_role_id=f"{self.prefix}role-1",
            )
        )

    @_in_own_tenant
    async def renew(self, token: str, client: str = CLIENT, base: str = BASE_URL_A) -> None:
        await self.renew_link.execute(
            RenewLinkCommand(token=token, client=client, link_base_url=base)
        )

    # -- reading back ---------------------------------------------------------------------

    @_in_own_tenant
    async def events(self, event_type: str) -> list[OutboxMessage]:
        return await self.rig.events(event_type)

    def opened(self, message: OutboxMessage) -> dict[str, Any]:
        """The rendered content of one SendMessage, opened as the sender does."""
        return self.rig.opened(message)

    @_in_own_tenant
    async def latest(self) -> Any:
        async with self.factory() as uow:
            return await uow.capacity.latest(self.service_id)

    @_in_own_tenant
    async def counts(self) -> dict[str, int]:
        """The number of nodes of each kind a link request could change."""
        labels = (
            "LinkToken",
            "Observation",
            "Communication",
            "OutboxMessage",
            "AuditEvent",
            "IdempotencyRecord",
            "ReportFlag",
        )

        async def work(tx: AsyncManagedTransaction) -> dict[str, int]:
            found: dict[str, int] = {}
            for label in labels:
                result = await tx.run(
                    f"MATCH (n:{label} {{tenantId: $tenant}}) RETURN count(n) AS n"
                )
                found[label] = int((await result.single() or {"n": 0})["n"])
            return found

        return await read_tx(self.driver, work)

    @_in_own_tenant
    async def token_node(self, token: str) -> dict[str, Any]:
        async def work(tx: AsyncManagedTransaction) -> dict[str, Any]:
            result = await tx.run(
                "MATCH (t:LinkToken {tokenHash: $hash, tenantId: $tenant}) RETURN properties(t) "
                "AS props",
                hash=token_hash_of(token),
            )
            row = await result.single()
            assert row is not None, "the token is not stored"
            props: dict[str, Any] = row["props"]
            return props

        return await read_tx(self.driver, work)


def build_link_rig(
    factory: UnitOfWorkFactory,
    driver: AsyncDriver,
    tenant: str,
    *,
    clock: FixedClock | None = None,
    secrets: FixedSecretStore | None = None,
    cache: InMemoryCache | None = None,
    ids: SequentialIds | None = None,
    service_id: str = SERVICE_ID,
    prefix: str = "",
    phone: str = PHONE_HASH_1,
    reports: Any = None,
    confirms: Any = None,
    tokens_class: type[LinkTokenService] = LinkTokenService,
) -> LinkRig:
    """The rig on a unit-of-work factory. `reports` and `confirms` replace ReportCapacity and
    ConfirmCapacity, and `tokens_class` the link-token service (a test that needs one to refuse)."""
    shared_clock = clock or FixedClock(ANSWER_AT)
    shared_ids = ids or SequentialIds()
    store = secrets or new_secrets()
    memory = cache or InMemoryCache(shared_clock)
    sealer = AesGcmContentSealer(store)

    def tokens(repo: LinkTokenRepository) -> LinkTokenService:
        return tokens_class(repo, store, shared_clock)

    idempotency = UnitOfWorkIdempotency(factory)
    handler = CapacityLinkHandler(
        factory,
        shared_clock,
        shared_ids,
        tokens,
        sealer,
        reports or ReportCapacity(factory, shared_clock, shared_ids, idempotency),
        confirms or ConfirmCapacity(factory, shared_clock, shared_ids, idempotency),
    )
    purposes: LinkPurposes = {CAPACITY_PURPOSE: handler}
    return LinkRig(
        factory=factory,
        driver=driver,
        tenant=tenant,
        clock=shared_clock,
        cache=memory,
        secrets=store,
        sealer=sealer,
        ids=shared_ids,
        rig=build_rig(
            factory,
            driver,
            tenant,
            service_id=service_id,
            ids=shared_ids,
            prefix=prefix,
            clock=shared_clock,
        ),
        purposes=purposes,
        view_link=ViewLink(factory, shared_clock, store, memory, tokens, purposes),
        respond_link=RespondViaLink(factory, shared_clock, store, memory, tokens, purposes),
        renew_link=RenewLink(factory, shared_clock, store, memory, tokens, purposes),
        service_id=service_id,
        prefix=prefix,
        phone=phone,
    )
