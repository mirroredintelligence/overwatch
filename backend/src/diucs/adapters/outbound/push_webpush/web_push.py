"""Web Push sender (I14). Stub: the behaviour is written in the implement step."""

from typing import Any, Final

from diucs.application.ports.outbound.messaging import SendReceipt


VAPID_PRIVATE_KEY_SECRET: Final = "webpush-vapid-private-key"
PUSH_TTL_SECONDS: Final = 600
GONE: Final = "gone"


def vapid_private_key(secrets: Any) -> str:
    raise NotImplementedError


class WebPushSender:
    def __init__(self, vapid_private_key: str, vapid_subject: str, *, transport: Any = None) -> None:
        raise NotImplementedError

    async def send(
        self, subscription: dict[str, Any], title: str, body: str, url: str, *, urgency: str = "normal"
    ) -> SendReceipt:
        raise NotImplementedError
