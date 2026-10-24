"""Idempotent schema migrations for Neo4j Community 5."""

from neo4j import AsyncDriver

MIGRATIONS: list[tuple[str, str]] = []


async def apply_migrations(driver: AsyncDriver) -> list[str]:
    raise NotImplementedError
