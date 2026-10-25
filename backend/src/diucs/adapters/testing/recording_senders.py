"""Recording senders (P07): fakes for external providers only (DEC-002, DEC-004)."""

from typing import Any

from diucs.application.ports.outbound.messaging import SendReceipt


class RecordingSmsSender:
    def __init__(self) -> None:
        raise NotImplementedError

    async def send(self, to: str, text: str, message_id: str) -> SendReceipt:
        raise NotImplementedError

    def fail_next(self) -> None:
        raise NotImplementedError


class RecordingEmailSender:
    def __init__(self) -> None:
        raise NotImplementedError

    async def send(self, to: str, subject: str, text: str, html: str | None) -> SendReceipt:
        raise NotImplementedError

    def fail_next(self) -> None:
        raise NotImplementedError


class RecordingPushSender:
    def __init__(self) -> None:
        raise NotImplementedError

    async def send(
        self, subscription: dict[str, Any], title: str, body: str, url: str
    ) -> SendReceipt:
        raise NotImplementedError

    def fail_next(self) -> None:
        raise NotImplementedError
