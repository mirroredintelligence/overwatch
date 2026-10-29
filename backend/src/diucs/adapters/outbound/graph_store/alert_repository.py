"""Alert subscriptions and alerts on Neo4j (P17). Red stub: every function raises NotImplementedError.

The implementation follows the registration repository (P13): an alert is a Task with code
`acknowledge-alert` written through the resource store; a subscription is a platform node.
"""

from typing import Any

from neo4j import AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.domain.model.alerts import AlertRecord, AlertSubscription


def alert_to_fhir(alert: AlertRecord) -> dict[str, Any]:
    raise NotImplementedError("P17: alert_to_fhir")


def alert_from_fhir(resource: dict[str, Any]) -> AlertRecord:
    raise NotImplementedError("P17: alert_from_fhir")


def subscription_to_props(subscription: AlertSubscription) -> dict[str, Any]:
    raise NotImplementedError("P17: subscription_to_props")


def subscription_from_props(props: dict[str, Any]) -> AlertSubscription:
    raise NotImplementedError("P17: subscription_from_props")


class Neo4jAlertSubscriptionRepository:
    def __init__(self, tx: AsyncManagedTransaction) -> None:
        self._tx = tx

    async def get_for_practitioner(self, practitioner_id: str) -> AlertSubscription | None:
        raise NotImplementedError("P17: get_for_practitioner")

    async def save(self, subscription: AlertSubscription) -> None:
        raise NotImplementedError("P17: save")

    async def subscribers_for_kind(self, kind: Any) -> list[AlertSubscription]:
        raise NotImplementedError("P17: subscribers_for_kind")


class Neo4jAlertRepository:
    def __init__(self, tx: AsyncManagedTransaction, store: ResourceStore) -> None:
        self._tx = tx
        self._store = store

    async def add(self, alert: AlertRecord) -> None:
        raise NotImplementedError("P17: add")

    async def get(self, alert_id: str) -> AlertRecord | None:
        raise NotImplementedError("P17: get")

    async def save(self, alert: AlertRecord) -> None:
        raise NotImplementedError("P17: save")

    async def open_for_owner(self, practitioner_id: str) -> list[AlertRecord]:
        raise NotImplementedError("P17: open_for_owner")

    async def chain(self, alert_id: str) -> list[AlertRecord]:
        raise NotImplementedError("P17: chain")
