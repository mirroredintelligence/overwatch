"""Visit offers and visit settings on Neo4j (DEC-1309).

(:VisitOffer {id, tenantId, bookingId, reference, serviceId, practitionerId, need, sector, urgency,
              offeredAt, expiresAt, state, stateAt, sealedDetails, etaAt})
(:VisitOffer)-[:OFFERED_TO]->(:Practitioner)
(:VisitOffer)-[:FOR_SERVICE]->(:HealthcareService)
(:VisitSettings {practitionerId, tenantId, status, statusAt, location})

Plain nodes, not FHIR resources: an offer is a work item between the advisor and a practitioner, and
the clinical record of the visit stays the booking Task, which the offer names by `bookingId`. The
two relationships are what a graph query over who is offered what, and for which service, walks.

Every statement writes `tenantId: $tenant` on each node it matches, merges or creates (DEC-130,
DEC-132). Times are UTC instants. `sealedDetails` is ciphertext (AES-256-GCM, bound to the offer,
the tenant and the practitioner); the store never sees the address or contact in the clear, and no
statement returns or logs the sealed text except the one that reads an offer back for its owner.
Uniqueness of an offer id and of a practitioner's settings within a tenant is a constraint
(migration 0200).
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Final, Literal

from overwatch.adapters.outbound.graph_store.driver import ScopedTx, run_query
from overwatch.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery
from overwatch.adapters.outbound.graph_store.scenario import (
    Expect,
    Marked,
    NodeSpec,
    Scenario,
    SeedNode,
    SeedRel,
    TenantSeed,
)
from overwatch.domain.codes import Urgency
from overwatch.domain.errors import NotFound
from overwatch.domain.model.visit import (
    LocationChoice,
    ShiftStatus,
    VisitOffer,
    VisitSettings,
    VisitState,
)

_NOW: Final = datetime(2026, 10, 31, 9, 0, tzinfo=UTC)
_LATER: Final = datetime(2026, 10, 31, 11, 0, tzinfo=UTC)
_OLD: Final = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
_SINCE: Final = datetime(2026, 10, 31, 0, 0, tzinfo=UTC)

_PRACTITIONER: Final = SeedNode(
    "person",
    ("Resource", "Practitioner"),
    {"id": "p-1", "key": "Practitioner/p-1", "active": True, "displayName": Marked("Visitor")},
)
_OTHER_PRACTITIONER: Final = SeedNode(
    "other",
    ("Resource", "Practitioner"),
    {"id": "p-2", "key": "Practitioner/p-2", "active": True, "displayName": Marked("Other")},
)
_SERVICE: Final = SeedNode(
    "service",
    ("Resource", "HealthcareService"),
    {"id": "svc-1", "key": "HealthcareService/svc-1", "active": True, "name": Marked("Round")},
)


def _offer_node(
    ref: str,
    offer_id: str,
    *,
    booking: str,
    practitioner: str,
    state: str,
    state_at: datetime,
    reference: str,
    expires_at: datetime = _LATER,
) -> SeedNode:
    return SeedNode(
        ref,
        ("VisitOffer",),
        {
            "id": offer_id,
            "bookingId": booking,
            "reference": reference,
            "serviceId": "svc-1",
            "practitionerId": practitioner,
            "need": Marked("Fall, no injury"),
            "sector": "DT4 8",
            "urgency": "within-2-hrs",
            "offeredAt": _OLD,
            "expiresAt": expires_at,
            "state": state,
            "stateAt": state_at,
            "sealedDetails": Marked("sealed"),
            "etaAt": None,
        },
    )


_OFFER_SEED: Final = TenantSeed(
    nodes=(
        _PRACTITIONER,
        _OTHER_PRACTITIONER,
        _SERVICE,
        _offer_node(
            "o1",
            "vo-1",
            booking="bk-1",
            practitioner="p-1",
            state="accepted",
            state_at=_NOW,
            reference="4821",
        ),
        _offer_node(
            "o2",
            "vo-2",
            booking="bk-2",
            practitioner="p-2",
            state="offered",
            state_at=_OLD,
            reference="4822",
        ),
        _offer_node(
            "o3",
            "vo-3",
            booking="bk-3",
            practitioner="p-1",
            state="declined",
            state_at=_OLD,
            reference="4823",
        ),
        _offer_node(
            "o4",
            "vo-4",
            booking="bk-4",
            practitioner="p-1",
            state="offered",
            state_at=_OLD,
            reference="4824",
            expires_at=_OLD,
        ),
    ),
    rels=(
        SeedRel("o1", "OFFERED_TO", "person"),
        SeedRel("o1", "FOR_SERVICE", "service"),
    ),
)

_ADD: Final = Scenario(
    "store an offer for the tenant's practitioner and service, beside the tenant's own offers",
    seed=_OFFER_SEED,
    params={
        "id": "vo-new",
        "bookingId": "bk-new",
        "reference": "4899",
        "serviceId": "svc-1",
        "practitionerId": "p-1",
        "need": "Chest pain",
        "sector": "DT1 2",
        "urgency": "today",
        "offeredAt": _NOW,
        "expiresAt": _LATER,
        "stateAt": _NOW,
        "sealedDetails": "sealed-text-new",
    },
    lookup=("serviceId", "practitionerId"),
    new=(
        "id",
        "bookingId",
        "reference",
        "need",
        "sector",
        "urgency",
        "offeredAt",
        "expiresAt",
        "stateAt",
        "sealedDetails",
    ),
    expect=Expect(
        rows=({"written": 1},),
        nodes={"VisitOffer": 1},
        rels={"OFFERED_TO": 1, "FOR_SERVICE": 1},
        after=(NodeSpec(("VisitOffer",), {"id": "vo-new", "state": "offered"}),),
    ),
)
_GET: Final = Scenario(
    "read the tenant's offer by its id",
    seed=_OFFER_SEED,
    params={"id": "vo-1"},
    lookup=("id",),
    expect=Expect(rows=({"id": "vo-1", "bookingId": "bk-1", "need": Marked("Fall, no injury")},)),
)
_FOR_BOOKING: Final = Scenario(
    "read the offers of one booking and no other booking's",
    seed=_OFFER_SEED,
    params={"bookingId": "bk-1"},
    lookup=("bookingId",),
    expect=Expect(rows=({"id": "vo-1"},)),
)
_FOR_PRACTITIONER: Final = Scenario(
    "read a practitioner's open offers, and not another practitioner's, an old declined one or "
    "one that ran out of time",
    seed=_OFFER_SEED,
    params={"practitionerId": "p-1", "since": _SINCE, "now": _NOW},
    lookup=("practitionerId",),
    new=("since", "now"),
    expect=Expect(rows=({"id": "vo-1"},)),
)
_CHANGE: Final = Scenario(
    "move the tenant's accepted offer on, only while it still holds the state expected",
    seed=_OFFER_SEED,
    params={
        "id": "vo-1",
        "expected": "accepted",
        "state": "on-my-way",
        "stateAt": _LATER,
        "sector": "DT4 8",
        "sealedDetails": None,
        "etaAt": _LATER,
    },
    lookup=("id",),
    new=("state", "stateAt", "etaAt"),
    expect=Expect(
        rows=({"n": 1},),
        after=(NodeSpec(("VisitOffer",), {"id": "vo-1", "state": "on-my-way"}),),
    ),
)
_SETTINGS_SEED: Final = TenantSeed(
    nodes=(
        _PRACTITIONER,
        SeedNode(
            "settings",
            ("VisitSettings",),
            {
                "practitionerId": "p-1",
                "status": "break",
                "statusAt": _NOW,
                "location": "never",
            },
        ),
    )
)
_SETTINGS_GET: Final = Scenario(
    "read the practitioner's settings",
    seed=_SETTINGS_SEED,
    params={"practitionerId": "p-1"},
    lookup=("practitionerId",),
    expect=Expect(rows=({"status": "break", "location": "never"},)),
)
_SETTINGS_SAVE: Final = Scenario(
    "replace the practitioner's settings in place",
    seed=_SETTINGS_SEED,
    params={
        "practitionerId": "p-1",
        "status": "available",
        "statusAt": _LATER,
        "location": "travel",
    },
    lookup=("practitionerId",),
    new=("status", "statusAt", "location"),
    expect=Expect(
        rows=({"n": 1},),
        after=(
            NodeSpec(
                ("VisitSettings",),
                {"practitionerId": "p-1", "status": "available", "location": "travel"},
            ),
        ),
    ),
)

_CYPHER: Final[dict[str, tuple[str, Literal["read", "write"], Scenario]]] = {
    "Q-VISIT-ADD": (
        "MATCH (p:Practitioner {id: $practitionerId, tenantId: $tenant}) "
        "MATCH (s:HealthcareService {id: $serviceId, tenantId: $tenant}) "
        "CREATE (o:VisitOffer {id: $id, tenantId: $tenant, bookingId: $bookingId, "
        "reference: $reference, serviceId: $serviceId, practitionerId: $practitionerId, "
        "need: $need, sector: $sector, urgency: $urgency, offeredAt: $offeredAt, "
        "expiresAt: $expiresAt, state: 'offered', stateAt: $stateAt, "
        "sealedDetails: $sealedDetails, etaAt: null}) "
        "CREATE (o)-[:OFFERED_TO]->(p) "
        "CREATE (o)-[:FOR_SERVICE]->(s) "
        "RETURN count(o) AS written",
        "write",
        _ADD,
    ),
    "Q-VISIT-GET": (
        "MATCH (o:VisitOffer {id: $id, tenantId: $tenant}) "
        "RETURN o.id AS id, o.bookingId AS bookingId, o.reference AS reference, "
        "o.serviceId AS serviceId, o.practitionerId AS practitionerId, o.need AS need, "
        "o.sector AS sector, o.urgency AS urgency, o.offeredAt AS offeredAt, "
        "o.expiresAt AS expiresAt, o.state AS state, o.stateAt AS stateAt, "
        "o.sealedDetails AS sealedDetails, o.etaAt AS etaAt",
        "read",
        _GET,
    ),
    "Q-VISIT-FOR-BOOKING": (
        "MATCH (o:VisitOffer {bookingId: $bookingId, tenantId: $tenant}) "
        "RETURN o.id AS id, o.bookingId AS bookingId, o.reference AS reference, "
        "o.serviceId AS serviceId, o.practitionerId AS practitionerId, o.need AS need, "
        "o.sector AS sector, o.urgency AS urgency, o.offeredAt AS offeredAt, "
        "o.expiresAt AS expiresAt, o.state AS state, o.stateAt AS stateAt, "
        "o.sealedDetails AS sealedDetails, o.etaAt AS etaAt ORDER BY o.id",
        "read",
        _FOR_BOOKING,
    ),
    "Q-VISIT-FOR-PRACTITIONER": (
        "MATCH (o:VisitOffer {practitionerId: $practitionerId, tenantId: $tenant}) "
        "WHERE (o.state = 'offered' AND o.expiresAt > $now) "
        "OR o.state IN ['accepted', 'on-my-way', 'arrived'] OR o.stateAt >= $since "
        "RETURN o.id AS id, o.bookingId AS bookingId, o.reference AS reference, "
        "o.serviceId AS serviceId, o.practitionerId AS practitionerId, o.need AS need, "
        "o.sector AS sector, o.urgency AS urgency, o.offeredAt AS offeredAt, "
        "o.expiresAt AS expiresAt, o.state AS state, o.stateAt AS stateAt, "
        "o.sealedDetails AS sealedDetails, o.etaAt AS etaAt ORDER BY o.offeredAt, o.id",
        "read",
        _FOR_PRACTITIONER,
    ),
    "Q-VISIT-CHANGE": (
        "MATCH (o:VisitOffer {id: $id, tenantId: $tenant, state: $expected}) "
        "SET o.state = $state, o.stateAt = $stateAt, o.sector = $sector, "
        "o.sealedDetails = $sealedDetails, o.etaAt = $etaAt "
        "RETURN count(o) AS n",
        "write",
        _CHANGE,
    ),
    "Q-VISIT-SETTINGS-GET": (
        "MATCH (v:VisitSettings {practitionerId: $practitionerId, tenantId: $tenant}) "
        "RETURN v.status AS status, v.statusAt AS statusAt, v.location AS location",
        "read",
        _SETTINGS_GET,
    ),
    "Q-VISIT-SETTINGS-SAVE": (
        "MERGE (v:VisitSettings {practitionerId: $practitionerId, tenantId: $tenant}) "
        "SET v.status = $status, v.statusAt = $statusAt, v.location = $location "
        "RETURN count(v) AS n",
        "write",
        _SETTINGS_SAVE,
    ),
}

for _query_id, (_text, _mode, _scenario) in _CYPHER.items():
    REGISTRY.register(NamedQuery(id=_query_id, cypher=_text, mode=_mode, scenario=_scenario))


def _utc(value: Any) -> datetime | None:
    if value is None:
        return None
    native: datetime = value.to_native()
    return native.astimezone(UTC)


def _required_utc(value: Any) -> datetime:
    moment = _utc(value)
    if moment is None:
        raise ValueError("a stored offer has no time")
    return moment


def _offer(row: dict[str, Any]) -> VisitOffer:
    return VisitOffer(
        id=str(row["id"]),
        booking_id=str(row["bookingId"]),
        reference=str(row["reference"]),
        service_id=str(row["serviceId"]),
        practitioner_id=str(row["practitionerId"]),
        need=str(row["need"]),
        sector=str(row["sector"]),
        urgency=Urgency(str(row["urgency"])),
        offered_at=_required_utc(row["offeredAt"]),
        expires_at=_required_utc(row["expiresAt"]),
        state=VisitState(str(row["state"])),
        state_at=_required_utc(row["stateAt"]),
        sealed_details=None if row["sealedDetails"] is None else str(row["sealedDetails"]),
        eta_at=_utc(row["etaAt"]),
    )


class Neo4jVisitRepository:
    def __init__(self, tx: ScopedTx) -> None:
        self._tx = tx

    async def add_many(self, offers: Sequence[VisitOffer]) -> None:
        for offer in offers:
            if offer.state is not VisitState.OFFERED or offer.sealed_details is None:
                raise ValueError("a new offer is offered and carries its sealed details")
            rows = await self._run(
                "Q-VISIT-ADD",
                id=offer.id,
                bookingId=offer.booking_id,
                reference=offer.reference,
                serviceId=offer.service_id,
                practitionerId=offer.practitioner_id,
                need=offer.need,
                sector=offer.sector,
                urgency=offer.urgency.value,
                offeredAt=offer.offered_at.astimezone(UTC),
                expiresAt=offer.expires_at.astimezone(UTC),
                stateAt=offer.state_at.astimezone(UTC),
                sealedDetails=offer.sealed_details,
            )
            if not rows or int(rows[0]["written"]) != 1:
                raise NotFound("the practitioner or the service of this offer")

    async def get(self, offer_id: str) -> VisitOffer | None:
        rows = await self._run("Q-VISIT-GET", id=offer_id)
        return _offer(rows[0]) if rows else None

    async def for_booking(self, booking_id: str) -> list[VisitOffer]:
        return [_offer(row) for row in await self._run("Q-VISIT-FOR-BOOKING", bookingId=booking_id)]

    async def for_practitioner(
        self, practitioner_id: str, since: datetime, now: datetime
    ) -> list[VisitOffer]:
        rows = await self._run(
            "Q-VISIT-FOR-PRACTITIONER",
            practitionerId=practitioner_id,
            since=since.astimezone(UTC),
            now=now.astimezone(UTC),
        )
        return [_offer(row) for row in rows]

    async def change(self, offer: VisitOffer, expected: VisitState) -> bool:
        rows = await self._run(
            "Q-VISIT-CHANGE",
            id=offer.id,
            expected=expected.value,
            state=offer.state.value,
            stateAt=offer.state_at.astimezone(UTC),
            sector=offer.sector,
            sealedDetails=offer.sealed_details,
            etaAt=None if offer.eta_at is None else offer.eta_at.astimezone(UTC),
        )
        return bool(rows) and int(rows[0]["n"]) == 1

    async def settings(self, practitioner_id: str) -> VisitSettings | None:
        rows = await self._run("Q-VISIT-SETTINGS-GET", practitionerId=practitioner_id)
        if not rows:
            return None
        row = rows[0]
        return VisitSettings(
            practitioner_id=practitioner_id,
            status=None if row["status"] is None else ShiftStatus(str(row["status"])),
            status_at=_utc(row["statusAt"]),
            location=LocationChoice(str(row["location"])),
        )

    async def save_settings(self, settings: VisitSettings) -> None:
        await self._run(
            "Q-VISIT-SETTINGS-SAVE",
            practitionerId=settings.practitioner_id,
            status=None if settings.status is None else settings.status.value,
            statusAt=None if settings.status_at is None else settings.status_at.astimezone(UTC),
            location=settings.location.value,
        )

    async def _run(self, query_id: str, **params: Any) -> list[dict[str, Any]]:
        query: NamedQuery = REGISTRY.get(query_id)
        return await run_query(self._tx, query, **params)
