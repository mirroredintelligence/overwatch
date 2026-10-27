"""Twilio SMS adapter (I06): sends a text and maps Twilio's status callbacks. DEC-002.

Stub for the red commit (DEC-010): names and signatures only, behaviour not yet written.
"""

from collections.abc import Mapping

import httpx

from diucs.application.ports.outbound.messaging import DeliveryUpdate, SendReceipt


def to_e164_uk(number: str) -> str:
    return ""


def parse_status_callback(form: Mapping[str, str]) -> DeliveryUpdate:
    return DeliveryUpdate("", "queued", None)


class TwilioSms:
    def __init__(
        self,
        client: httpx.AsyncClient,
        account_sid: str,
        auth_token: str,
        from_number: str,
        status_callback_url: str,
    ) -> None:
        self._client = client
        self._account_sid = account_sid
        self._auth_token = auth_token
        self._from_number = from_number
        self._status_callback_url = status_callback_url

    async def send(self, to: str, text: str, message_id: str) -> SendReceipt:
        return SendReceipt("", True)
