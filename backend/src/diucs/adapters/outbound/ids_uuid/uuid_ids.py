"""Identifier generator that returns random UUID4 strings."""


class UuidGenerator:
    def new_id(self) -> str:
        raise NotImplementedError
