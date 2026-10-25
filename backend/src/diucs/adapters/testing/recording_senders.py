"""Recording senders (P07): fakes for external providers only (DEC-002, DEC-004).

Each fake returns a receipt with a provider id (sms-1, sms-2, ...; email-n; push-n). Every send
consumes one number, so a refused send still has an id. Only accepted sends are kept in `sent`.
fail_next() refuses the next send only, which lets a test prove how a caller handles a refusal.
"""

from dataclasses import dataclass
from typing import Any

from diucs.application.ports.outbound.messaging import SendReceipt


@dataclass(frozen=True, slots=True)
class RecordedSms:
    to: str
    text: str
    message_id: str


@dataclass(frozen=True, slots=True)
class RecordedEmail:
    to: str
    subject: str
    text: str
    html: str | None


@dataclass(frozen=True, slots=True)
class RecordedPush:
    subscription: dict[str, Any]
    title: str
    body: str
    url: str


class _Attempts:
    """Numbers the provider ids and remembers whether the next send is to be refused."""

    def __init__(self, prefix: str) -> None:
        self._prefix = prefix
        self._count = 0
        self._refuse_next = False

    def fail_next(self) -> None:
        self._refuse_next = True

    def next_receipt(self) -> SendReceipt:
        self._count += 1
        accepted = not self._refuse_next
        self._refuse_next = False
        return SendReceipt(f"{self._prefix}-{self._count}", accepted)


class RecordingSmsSender:
    def __init__(self) -> None:
        self.sent: list[RecordedSms] = []
        self._attempts = _Attempts("sms")

    async def send(self, to: str, text: str, message_id: str) -> SendReceipt:
        receipt = self._attempts.next_receipt()
        if receipt.accepted:
            self.sent.append(RecordedSms(to, text, message_id))
        return receipt

    def fail_next(self) -> None:
        self._attempts.fail_next()


class RecordingEmailSender:
    def __init__(self) -> None:
        self.sent: list[RecordedEmail] = []
        self._attempts = _Attempts("email")

    async def send(self, to: str, subject: str, text: str, html: str | None) -> SendReceipt:
        receipt = self._attempts.next_receipt()
        if receipt.accepted:
            self.sent.append(RecordedEmail(to, subject, text, html))
        return receipt

    def fail_next(self) -> None:
        self._attempts.fail_next()


class RecordingPushSender:
    def __init__(self) -> None:
        self.sent: list[RecordedPush] = []
        self._attempts = _Attempts("push")

    async def send(
        self, subscription: dict[str, Any], title: str, body: str, url: str
    ) -> SendReceipt:
        receipt = self._attempts.next_receipt()
        if receipt.accepted:
            self.sent.append(RecordedPush(dict(subscription), title, body, url))
        return receipt

    def fail_next(self) -> None:
        self._attempts.fail_next()
