"""A recording stand-in for the reporter session store (U37, R11): it keeps a per-person epoch the
way the Redis store does, so a use case's order of calls and a sign-in's epoch check can be tested
without Redis. A test double for a unit test, not a store of record (DEC-004: sessions are not a
record)."""

from datetime import datetime

from diucs.application.ports.outbound.identity import ReporterSession, SessionEpochChanged
from diucs.domain.codes import Role


class StubSessions:
    def __init__(self, events: list[str] | None = None) -> None:
        self.events = events if events is not None else []
        self.epochs: dict[str, int] = {}
        self.sessions: dict[str, ReporterSession] = {}
        self.fail = False
        """When true, `delete_all_for_person` raises, as a Redis that cannot be reached would."""
        self._next = 0

    async def epoch(self, practitioner_id: str) -> int:
        return self.epochs.get(practitioner_id, 0)

    async def create(
        self,
        role: Role,
        practitioner_id: str,
        device_id: str,
        services: tuple[str, ...],
        now: datetime,
        *,
        epoch: int,
    ) -> str:
        if epoch != self.epochs.get(practitioner_id, 0):
            raise SessionEpochChanged
        self._next += 1
        session_id = f"session-{self._next}"
        self.sessions[session_id] = ReporterSession(
            session_id=session_id,
            role=role,
            practitioner_id=practitioner_id,
            device_id=device_id,
            services=services,
            created=now,
            last_seen=now,
            epoch=epoch,
        )
        return session_id

    async def get(self, session_id: str) -> ReporterSession | None:
        session = self.sessions.get(session_id)
        if session is None or session.epoch != self.epochs.get(session.practitioner_id, 0):
            return None
        return session

    async def touch(self, session_id: str, now: datetime) -> bool:
        return await self.get(session_id) is not None

    async def delete(self, session_id: str) -> None:
        self.sessions.pop(session_id, None)

    async def delete_all_for_person(self, practitioner_id: str) -> None:
        self.events.append("sessions.revoke")
        if self.fail:
            raise OSError("redis unreachable")
        self.epochs[practitioner_id] = self.epochs.get(practitioner_id, 0) + 1
        for session_id in [
            sid for sid, held in self.sessions.items() if held.practitioner_id == practitioner_id
        ]:
            del self.sessions[session_id]
