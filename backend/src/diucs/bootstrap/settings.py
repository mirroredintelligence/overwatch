"""STUB (DEC-010): the class name and fields are declared, the behaviour is not yet built."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    neo4j_password: SecretStr = SecretStr("diucs-test-password")

    def __init__(self, **values: object) -> None:
        raise NotImplementedError
