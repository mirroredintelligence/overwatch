"""Pure tests of the push subscription store (P19): the JSON the device holds, the checks of a
subscription, the statement shape and the rule that the secret is never echoed. The Neo4j behaviour
is in tests/integration/graph_store/test_push_subscription_repository.py.
"""

import re
from datetime import UTC, datetime
from typing import Any

import pytest

from diucs.adapters.outbound.graph_store import push_subscription_repository  # noqa: F401
from diucs.adapters.outbound.graph_store.push_subscription_repository import (
    checked_subscription,
    subscription_from_json,
    subscription_json,
)
from diucs.adapters.outbound.graph_store.queries import REGISTRY
from diucs.adapters.outbound.graph_store.scenario import validate_scenario
from diucs.adapters.outbound.graph_store.unconverted import UNCONVERTED
from diucs.application.ports.outbound.messaging import PushSubscription
from diucs.domain.errors import ValidationFailed

SAVED = datetime(2026, 10, 25, 13, 12, tzinfo=UTC)
ENDPOINT = "https://push.example/abc"
SUBSCRIPTION: dict[str, Any] = {"endpoint": ENDPOINT, "keys": {"p256dh": "k1", "auth": "a1"}}


def test_a_subscription_round_trips_through_its_json() -> None:
    assert subscription_from_json(subscription_json(SUBSCRIPTION)) == SUBSCRIPTION


def test_the_json_is_the_same_text_whatever_the_key_order() -> None:
    reordered = {"keys": {"auth": "a1", "p256dh": "k1"}, "endpoint": ENDPOINT}

    assert subscription_json(reordered) == subscription_json(SUBSCRIPTION)


def test_a_valid_subscription_passes_the_check() -> None:
    checked_subscription(SUBSCRIPTION)


@pytest.mark.parametrize(
    "bad",
    [
        {"keys": {"p256dh": "k1", "auth": "a1"}},
        {"endpoint": "", "keys": {"p256dh": "k1", "auth": "a1"}},
        {"endpoint": ENDPOINT},
        {"endpoint": ENDPOINT, "keys": {"p256dh": "k1"}},
        {"endpoint": ENDPOINT, "keys": {"p256dh": "", "auth": "a1"}},
        {"endpoint": 42, "keys": {"p256dh": "k1", "auth": "a1"}},
    ],
)
def test_a_subscription_without_an_endpoint_and_both_keys_is_refused(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationFailed) as refused:
        checked_subscription(bad)

    assert refused.value.field == "subscription"


def test_a_refusal_never_echoes_the_endpoint_or_the_keys() -> None:
    bad = {"endpoint": ENDPOINT, "keys": {"p256dh": "k1"}}

    with pytest.raises(ValidationFailed) as refused:
        checked_subscription(bad)

    text = str(refused.value)
    assert ENDPOINT not in text
    assert "k1" not in text


def test_a_push_subscription_is_a_frozen_value() -> None:
    subscription = PushSubscription(
        device_id="dev-1", practitioner_id="p1", subscription=SUBSCRIPTION, saved_at=SAVED
    )

    with pytest.raises(AttributeError):
        subscription.device_id = "dev-2"  # type: ignore[misc]


def test_the_push_statements_are_registered() -> None:
    assert {"Q-PUSH-SAVE", "Q-PUSH-FOR", "Q-PUSH-DELETE"} <= set(REGISTRY.ids())


def test_every_push_statement_names_its_tenant_and_carries_a_valid_scenario() -> None:
    pattern = re.compile(r"\((?:\w+)?(?::\w+)+\s*(\{[^}]*\})?\)")
    ids = [q for q in REGISTRY.ids() if q.startswith("Q-PUSH")]
    assert ids
    for query_id in ids:
        query = REGISTRY.get(query_id)
        for match in pattern.finditer(query.cypher):
            assert match.group(1) is not None and "tenantId: $tenant" in match.group(1), query_id
        assert query.scenario is not None, query_id
        assert validate_scenario(query_id, query.scenario) == [], query_id
        assert query_id not in UNCONVERTED


def test_no_push_statement_writes_the_subscription_text_into_a_log_or_an_audit_row() -> None:
    # The subscription JSON is stored on the Device only; no statement copies it elsewhere.
    for query_id in REGISTRY.ids():
        if query_id.startswith("Q-PUSH"):
            continue
        assert "pushSubscriptionJson" not in REGISTRY.get(query_id).cypher, query_id
