"""The Neo4j test container password (F11).

A password that starts with "-" makes neo4j-admin reject the NEO4J_AUTH value as an option, so the
container exits at once with "Missing required parameter: '<password>'" (exit 64). token_urlsafe
can produce such a password, about one time in 64, so the harness must never generate one.
"""

import re

from tests.support.neo4j import new_container_password

SAMPLES = 5000


def test_generated_password_is_hex_and_never_starts_with_a_dash() -> None:
    for _ in range(SAMPLES):
        password = new_container_password()
        assert re.fullmatch(r"[0-9a-f]{32}", password), password
