"""Twilio inbound SMS webhook (I07). Stub for the red run: every route answers 501."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from fastapi import APIRouter, Response

from diucs.adapters.outbound.sms_twilio.twilio_sms import parse_status_callback
from diucs.application.ports.outbound.cache import Cache
from diucs.application.ports.outbound.event_bus import EventBus
from diucs.application.ports.outbound.identity import PhoneHasher
from diucs.application.ports.outbound.tenant_lines import InboundLineDirectory
from diucs.application.ports.outbound.tokens import SecretStore

REPLY_PATH: Final = "/webhooks/sms/twilio"
STATUS_PATH: Final = "/webhooks/sms/twilio/status"


@dataclass(frozen=True, slots=True)
class SmsWebhookDeps:
    cache: Cache
    event_bus: EventBus
    hasher: PhoneHasher
    secrets: SecretStore
    lines: InboundLineDirectory
    public_base_url: str


def twilio_signature(url: str, params: Mapping[str, str], token: str | bytes) -> str:
    return ""


_STATUS_PARSER = parse_status_callback

router = APIRouter()


@router.post(REPLY_PATH)
async def sms_reply() -> Response:
    return Response(status_code=501)


@router.post(STATUS_PATH)
async def sms_status() -> Response:
    return Response(status_code=501)
