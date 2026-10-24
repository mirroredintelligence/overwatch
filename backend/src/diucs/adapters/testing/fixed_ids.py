"""Test identifier generator that counts up: prefix-1, prefix-2, ..."""


class SequentialIds:
    def __init__(self, prefix: str = "id") -> None:
        self._prefix = prefix

    def new_id(self) -> str:
        raise NotImplementedError
