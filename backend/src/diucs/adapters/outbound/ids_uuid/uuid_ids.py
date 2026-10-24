"""Identifier generator that returns random UUID4 strings."""

import uuid


class UuidGenerator:
    def new_id(self) -> str:
        return str(uuid.uuid4())
