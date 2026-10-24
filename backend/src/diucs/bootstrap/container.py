"""STUB (DEC-010): names and signatures only, no behaviour yet."""

from dataclasses import dataclass

from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.bootstrap.settings import Settings


@dataclass(frozen=True)
class Container:
    clock: Clock
    ids: IdGenerator


def build(settings: Settings) -> Container:
    raise NotImplementedError


def build_for_tests(clock: Clock | None = None, ids: IdGenerator | None = None) -> Container:
    raise NotImplementedError
