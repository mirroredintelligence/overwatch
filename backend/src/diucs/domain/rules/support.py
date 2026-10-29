"""Support access rules (O06). Stub for the red commit."""

from datetime import datetime


def normalise_support_code(text: object) -> str | None:
    raise NotImplementedError


def hash_support_code(code: str, secret: bytes) -> str:
    raise NotImplementedError


def code_window(now: datetime) -> datetime:
    raise NotImplementedError


def access_window(now: datetime) -> datetime:
    raise NotImplementedError


def support_code_usable(expires_at: datetime, stopped_at: datetime | None, now: datetime) -> bool:
    raise NotImplementedError


def is_lead(roles: object, practitioner_active: bool) -> bool:
    raise NotImplementedError


def may_open_support(role: object) -> bool:
    raise NotImplementedError
