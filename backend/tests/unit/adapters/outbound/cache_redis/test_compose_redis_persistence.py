"""The local Redis keeps its data across restarts (DEC-091): append-only file on a named volume.

Reads infra/docker-compose.yml. No Docker is needed.
"""

from pathlib import Path
from typing import Any

import yaml

COMPOSE = Path(__file__).resolve().parents[6] / "infra" / "docker-compose.yml"


def _redis_service() -> dict[str, Any]:
    compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    service: dict[str, Any] = compose["services"]["redis"]
    return service


def test_redis_starts_with_append_only_persistence() -> None:
    command = _redis_service().get("command")
    args = command if isinstance(command, list) else str(command).split()
    assert "--appendonly" in args
    assert args[args.index("--appendonly") + 1] == "yes"


def test_redis_data_directory_is_a_named_volume_declared_at_top_level() -> None:
    compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    mounts = _redis_service().get("volumes", [])
    named = [m.split(":")[0] for m in mounts if m.split(":")[-1] == "/data"]
    assert len(named) == 1
    assert named[0] in compose["volumes"]
