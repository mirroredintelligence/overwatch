"""Web Push subscriptions on Neo4j (P19). Red stub: every method raises NotImplementedError."""

from typing import Any

from neo4j import AsyncManagedTransaction

from diucs.application.ports.outbound.messaging import PushSubscription


def subscription_json(subscription: dict[str, Any]) -> str:
    raise NotImplementedError("P19: subscription_json")


def subscription_from_json(text: str) -> dict[str, Any]:
    raise NotImplementedError("P19: subscription_from_json")


def checked_subscription(subscription: dict[str, Any]) -> None:
    raise NotImplementedError("P19: checked_subscription")


class Neo4jPushSubscriptionRepository:
    def __init__(self, tx: AsyncManagedTransaction) -> None:
        self._tx = tx

    async def save(self, subscription: PushSubscription) -> None:
        raise NotImplementedError("P19: save")

    async def for_practitioner(self, practitioner_id: str) -> list[PushSubscription]:
        raise NotImplementedError("P19: for_practitioner")

    async def delete(self, device_id: str) -> None:
        raise NotImplementedError("P19: delete")
