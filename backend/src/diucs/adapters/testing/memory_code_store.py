"""Test fakes for text codes (P16, DEC-070): the code store (Redis in production, I13) and a sender
that records the codes it is asked to send.

These are fakes for a non-record store and for an external provider (DEC-004). The code store is
not a record of truth: a code is valid for ten minutes (CODE_VALID_FOR), and its state is lost on
restart in production by design.
"""

from dataclasses import dataclass
from datetime import UTC

from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.identity import CodeResendRefused
from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.identity_policy import CODE_VALID_FOR, CodeState, can_resend, check_purpose


class InMemoryCodeStore:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._codes: dict[tuple[str, str], tuple[str, CodeState]] = {}

    async def save(self, purpose: str, phone_hash: str, code_hash: str, state: CodeState) -> None:
        check_purpose(purpose)
        if state.issued_at.tzinfo is None or state.issued_at.utcoffset() is None:
            raise ValidationFailed("issued_at", "must be a timezone-aware datetime")
        key = (purpose, phone_hash)
        current = self._codes.get(key)
        # A different code within the resend cooldown of the one it replaces is refused (I13).
        if (
            current is not None
            and current[0] != code_hash
            and not can_resend(current[1].issued_at, state.issued_at)
        ):
            raise CodeResendRefused()
        self._codes[key] = (code_hash, state)

    async def get(self, purpose: str, phone_hash: str) -> tuple[str, CodeState] | None:
        """The code and its state while the code is valid. A code the clock has passed, or whose
        issue time is in the future, is dropped and reported as None (fail closed)."""
        key = (purpose, phone_hash)
        entry = self._codes.get(key)
        if entry is None:
            return None
        issued = entry[1].issued_at.astimezone(UTC)
        now = self._clock.now().astimezone(UTC)
        if issued <= now < issued + CODE_VALID_FOR:
            return entry
        del self._codes[key]
        return None

    async def clear(self, purpose: str, phone_hash: str) -> None:
        self._codes.pop((purpose, phone_hash), None)


@dataclass(frozen=True, slots=True)
class RecordedCode:
    phone: str
    code: str


class RecordingCodeSender:
    """Records every code it is asked to send, so a test can read the code a user would receive."""

    def __init__(self) -> None:
        self.sent: list[RecordedCode] = []

    async def send_code(self, phone: str, code: str) -> None:
        self.sent.append(RecordedCode(phone=phone, code=code))
