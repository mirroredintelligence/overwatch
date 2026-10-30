"""The Service Bus entities the network projector needs (TEN-055, DEC-545, DEC-132 item 4).

The projection queue, and the `network-projector` subscription on each topic whose events change
what a network shows. A subscription that was forgotten would silently never project, so this
reads the JSON the emulator is started with and compares it with the names the code uses. No
Docker.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from diucs.adapters.inbound.workers.network_projector import NETWORK_SUBSCRIPTION, network_runners
from diucs.application.ports.outbound.event_bus import QUEUES, TOPICS
from diucs.domain.events import PROJECTION_WORK

CONFIG = Path(__file__).resolve().parents[5] / "infra" / "servicebus-config.json"
README = Path(__file__).resolve().parents[5] / "infra" / "README.md"


def _namespace() -> dict[str, Any]:
    return json.loads(CONFIG.read_text(encoding="utf-8"))["UserConfig"]["Namespaces"][0]


def _queues() -> dict[str, dict[str, Any]]:
    return {q["Name"]: q["Properties"] for q in _namespace()["Queues"]}


def _subscriptions(topic: str) -> dict[str, dict[str, Any]]:
    found = next(t for t in _namespace()["Topics"] if t["Name"] == topic)
    return {s["Name"]: s["Properties"] for s in found["Subscriptions"]}


def test_every_queue_the_code_knows_is_declared_and_no_other() -> None:
    assert set(_queues()) == QUEUES


def test_every_topic_the_code_knows_is_declared() -> None:
    assert {t["Name"] for t in _namespace()["Topics"]} == TOPICS


def test_the_projection_queue_is_a_plain_queue_that_dead_letters_and_retries_like_the_others() -> (
    None
):
    properties = _queues()[PROJECTION_WORK]
    reference = _queues()["scheduled.work"]
    assert properties["RequiresSession"] is False
    assert properties["DeadLetteringOnMessageExpiration"] is True
    assert properties["MaxDeliveryCount"] == reference["MaxDeliveryCount"]
    assert properties["LockDuration"] == reference["LockDuration"]
    assert properties["DefaultMessageTimeToLive"] == reference["DefaultMessageTimeToLive"]


@pytest.mark.parametrize(
    ("topic", "sessions"),
    [
        ("capacity.events", True),
        ("booking.events", False),
        ("criteria.events", False),
        ("registration.events", False),
    ],
)
def test_the_network_projector_subscribes_to_each_producer_topic(
    topic: str, sessions: bool
) -> None:
    properties = _subscriptions(topic)[NETWORK_SUBSCRIPTION]
    assert properties["RequiresSession"] is sessions
    assert properties["DeadLetteringOnMessageExpiration"] is True
    assert properties["MaxDeliveryCount"] == 10


def test_the_config_and_the_runners_name_the_same_entities() -> None:
    """A runner over an entity the emulator does not declare would fail at the first receive."""
    for runner in network_runners(None, None, None, None):  # type: ignore[arg-type]
        if runner._subscription is None:
            assert runner._entity in _queues()
        else:
            subscriptions = _subscriptions(runner._entity)
            assert runner._subscription in subscriptions
            assert subscriptions[runner._subscription]["RequiresSession"] is runner._sessions


def test_the_other_topics_have_no_network_projector_subscription() -> None:
    for topic in ("alerts.events", "messages.outbound"):
        assert NETWORK_SUBSCRIPTION not in _subscriptions(topic)


def test_the_network_events_topic_is_declared_with_a_subscription_for_the_reconciliation() -> None:
    """The governance events (grant approved, grant ended, member left) are the backfill and end
    triggers. The topic and its subscription exist so a publish is never refused; the runner that
    reads it is the reconciliation sweep (TEN-056), not this task."""
    properties = _subscriptions("network.events")[NETWORK_SUBSCRIPTION]
    assert properties["RequiresSession"] is False
    assert properties["DeadLetteringOnMessageExpiration"] is True


def test_the_readme_names_the_queue_and_the_subscription() -> None:
    text = README.read_text(encoding="utf-8")
    assert PROJECTION_WORK in text
    assert NETWORK_SUBSCRIPTION in text
