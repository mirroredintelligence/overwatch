"""The Service Bus config filters each sender subscription on its channel (I10, DEC-131).

The sender subscriptions must each take only their own channel, so a text is never handed to the
email sender and the other way round. A subscription with no rule takes every message, which is the
gap the tenancy audit recorded (C-adapters-infra.md, messages.outbound). No Docker: this reads the
JSON the emulator is started with.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from diucs.adapters.inbound.workers.message_senders import (
    EMAIL_SUBSCRIPTION,
    MESSAGES_TOPIC,
    PUSH_SUBSCRIPTION,
    SMS_SUBSCRIPTION,
)

CONFIG = Path(__file__).resolve().parents[6] / "infra" / "servicebus-config.json"


def _subscriptions() -> dict[str, dict[str, Any]]:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    namespace = config["UserConfig"]["Namespaces"][0]
    topic = next(t for t in namespace["Topics"] if t["Name"] == MESSAGES_TOPIC)
    return {sub["Name"]: sub for sub in topic["Subscriptions"]}


@pytest.mark.parametrize(
    ("subscription", "channel"),
    [(SMS_SUBSCRIPTION, "text"), (EMAIL_SUBSCRIPTION, "email"), (PUSH_SUBSCRIPTION, "push")],
)
def test_each_sender_subscription_takes_only_its_own_channel(
    subscription: str, channel: str
) -> None:
    rules = _subscriptions()[subscription].get("Rules", [])

    assert len(rules) == 1
    sql = rules[0]["Properties"]["SqlFilter"]["SqlExpression"]
    assert sql == f"channel = '{channel}'"
    assert rules[0]["Properties"]["FilterType"] == "SqlFilter"


def test_the_sender_subscriptions_are_the_only_ones_on_messages_outbound() -> None:
    assert set(_subscriptions()) == {SMS_SUBSCRIPTION, EMAIL_SUBSCRIPTION, PUSH_SUBSCRIPTION}
