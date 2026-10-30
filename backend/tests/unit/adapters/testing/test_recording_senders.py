"""Unit tests for the recording senders (P07). They stand in for external providers only."""

from diucs.adapters.testing.recording_senders import (
    RecordingEmailSender,
    RecordingPushSender,
    RecordingSmsSender,
)
from diucs.application.ports.outbound.messaging import SendReceipt

SAMPLE_MOBILE = "07700900123"
SAMPLE_SUBSCRIPTION = {
    "endpoint": "https://push.example/sub/1",
    "keys": {"p256dh": "k", "auth": "a"},
}


async def test_the_first_sms_is_accepted_with_provider_id_sms_1() -> None:
    sender = RecordingSmsSender()
    receipt = await sender.send(SAMPLE_MOBILE, "hello", "C1")
    assert receipt == SendReceipt("sms-1", True)


async def test_fail_next_refuses_only_the_next_sms() -> None:
    sender = RecordingSmsSender()
    sender.fail_next()
    refused = await sender.send(SAMPLE_MOBILE, "first", "C1")
    accepted = await sender.send(SAMPLE_MOBILE, "second", "C1")
    assert refused.accepted is False
    assert accepted.accepted is True


async def test_only_accepted_sms_are_kept_in_sent() -> None:
    sender = RecordingSmsSender()
    sender.fail_next()
    await sender.send(SAMPLE_MOBILE, "refused text", "C1")
    await sender.send(SAMPLE_MOBILE, "hello", "C2")
    assert [(m.to, m.text, m.message_id) for m in sender.sent] == [(SAMPLE_MOBILE, "hello", "C2")]


async def test_an_email_is_recorded_with_its_subject_and_body() -> None:
    sender = RecordingEmailSender()
    receipt = await sender.send(
        "ops@example.test", "UCR West: confirm", "Reply Y", "<p>Reply Y</p>"
    )
    assert receipt.accepted is True
    recorded = sender.sent[0]
    assert recorded.subject == "UCR West: confirm"
    assert recorded.text == "Reply Y"
    assert recorded.html == "<p>Reply Y</p>"


async def test_a_refused_email_is_not_recorded_as_sent() -> None:
    sender = RecordingEmailSender()
    sender.fail_next()
    receipt = await sender.send("ops@example.test", "subject", "text", None)
    assert receipt.accepted is False
    assert sender.sent == []


async def test_a_push_is_recorded_with_its_title_body_and_url() -> None:
    sender = RecordingPushSender()
    receipt = await sender.send(
        SAMPLE_SUBSCRIPTION, "Capacity", "Reply by 12:30", "https://diucs.example/r"
    )
    assert receipt.accepted is True
    recorded = sender.sent[0]
    assert recorded.title == "Capacity"
    assert recorded.body == "Reply by 12:30"
    assert recorded.url == "https://diucs.example/r"
    assert recorded.subscription == SAMPLE_SUBSCRIPTION


async def test_fail_next_on_push_refuses_the_next_push_only() -> None:
    sender = RecordingPushSender()
    sender.fail_next()
    assert (await sender.send(SAMPLE_SUBSCRIPTION, "t", "b", "u")).accepted is False
    assert (await sender.send(SAMPLE_SUBSCRIPTION, "t", "b", "u")).accepted is True


# Which tenant and which identity sent (TEN-042)

from diucs.adapters.testing.recording_senders import FixedSenderResolver  # noqa: E402
from diucs.application.tenancy import bind_tenant  # noqa: E402


async def test_a_text_records_the_tenant_bound_when_it_was_sent_and_the_identity_it_left_from() -> (
    None
):
    sender = RecordingSmsSender(identity="+447700900001")

    with bind_tenant("tenant-a"):
        await sender.send(SAMPLE_MOBILE, "hello", "C1")

    [recorded] = sender.sent
    assert recorded.tenant == "tenant-a"
    assert recorded.identity == "+447700900001"


async def test_an_email_records_the_tenant_bound_and_the_identity() -> None:
    sender = RecordingEmailSender(identity="ops@alpha.example.test")

    with bind_tenant("tenant-b"):
        await sender.send("ops@example.test", "subject", "text", None)

    [recorded] = sender.sent
    assert recorded.tenant == "tenant-b"
    assert recorded.identity == "ops@alpha.example.test"


async def test_a_send_with_no_tenant_bound_records_none_and_is_not_refused() -> None:
    sender = RecordingSmsSender()

    await sender.send(SAMPLE_MOBILE, "hello", "C1")

    assert sender.sent[0].tenant is None
    assert sender.sent[0].identity is None


async def test_the_fixed_resolver_gives_each_tenant_its_own_recording_sender() -> None:
    first, second = RecordingEmailSender(identity="a"), RecordingEmailSender(identity="b")
    resolver = FixedSenderResolver(email={"tenant-a": first, "tenant-b": second})

    with bind_tenant("tenant-a"):
        sender_a = await resolver.email_for(None)
        await sender_a.send("x@example.test", "s", "t", None)
    with bind_tenant("tenant-b"):
        sender_b = await resolver.email_for(None)
        await sender_b.send("x@example.test", "s", "t", None)

    assert [m.tenant for m in first.sent] == ["tenant-a"]
    assert [m.tenant for m in second.sent] == ["tenant-b"]
