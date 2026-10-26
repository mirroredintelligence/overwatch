"""Test fakes for text codes (P16): the code store (Redis in production, I13) and the sender that
records codes. Stub for the red commit (DEC-010)."""

from diucs.application.ports.outbound.clock import Clock
from diucs.domain.rules.identity_policy import CodeState


class InMemoryCodeStore:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    async def save(self, phone_hash: str, code_hash: str, state: CodeState) -> None:
        raise NotImplementedError

    async def get(self, phone_hash: str) -> tuple[str, CodeState] | None:
        raise NotImplementedError

    async def clear(self, phone_hash: str) -> None:
        raise NotImplementedError


class RecordingCodeSender:
    async def send_code(self, phone: str, code: str) -> None:
        raise NotImplementedError
