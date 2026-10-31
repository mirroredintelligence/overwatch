"""The Service Bus config holds the topic and the subscription of the code sender (KI-270, N1).

`codes.dispatch` was published to by RequestTextCode and was in no topology, so no text code was
ever sent. The topic has one subscription, `code-sender`, that takes every message (the consumer
itself acts on SendCode alone and discards DiscardCode). No Docker: this reads the JSON the
emulator is started with.
"""

import json
from pathlib import Path
from typing import Any

from diucs.adapters.inbound.workers.code_sender import CODE_SUBSCRIPTION, CODES_TOPIC

from diucs.application.ports.outbound.event_bus import TOPICS

CONFIG = Path(__file__).resolve().parents[6] / "infra" / "servicebus-config.json"


def _topic() -> dict[str, Any]:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    namespace = config["UserConfig"]["Namespaces"][0]
    return next(t for t in namespace["Topics"] if t["Name"] == CODES_TOPIC)


def test_the_topic_is_in_the_bus_port_and_in_the_config() -> None:
    assert CODES_TOPIC in TOPICS
    assert _topic()["Name"] == "codes.dispatch"


def test_the_topic_has_one_subscription_the_code_sender_reads() -> None:
    subscriptions = _topic()["Subscriptions"]

    assert [s["Name"] for s in subscriptions] == [CODE_SUBSCRIPTION]
    properties = subscriptions[0]["Properties"]
    assert properties["RequiresSession"] is False
    assert properties["MaxDeliveryCount"] == 10
    assert properties["DeadLetteringOnMessageExpiration"] is True
    assert "Rules" not in subscriptions[0]


def test_a_code_message_does_not_outlive_the_code() -> None:
    # A code is valid for ten minutes (CODE_VALID_FOR); the topology default of an hour is the
    # same as the other topics, and the consumer drops a code older than ten minutes itself.
    assert _topic()["Properties"]["DefaultMessageTimeToLive"] == "PT1H"
