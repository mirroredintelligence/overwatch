"""The platform operator's network creation, offboarding, export and purge, wired (TEN-077,
TEN-074, DEC-960 to DEC-971): `scripts/tenant_lifecycle.py`.

The composition root of the operator's second set of lifecycle steps, beside `provisioning.py`
(which creates, activates and suspends): the use cases of `network_admin.py`, `tenant_offboard.py`
and `tenant_purge.py` built on one container, and the command line that runs them. It is in
bootstrap, the one layer that may name the adapters, bind a tenant and read the settings. Nothing
here holds a rule.

Each command acts on one tenant (the one named, bound for the command and for nothing else) as the
platform operator named with `--operator`, who has no standing in any other scope and no data
access of its own. It prints fixed words, ids and counts, and no value of any tenant's data.

    tenant_lifecycle.py --operator NAME network-create OWNER-TENANT NETWORK-ID --name N
        --agreement-reference R --agreement-version V --system-name S --pathway-name P
    tenant_lifecycle.py --operator NAME offboard TENANT --confirm TENANT
    tenant_lifecycle.py --operator NAME export TENANT --out DIR [--protected]
    tenant_lifecycle.py --operator NAME complete-offboarding TENANT
        [--manifest HASH] [--export-waived] [--notice-waived]
    tenant_lifecycle.py --operator NAME purge TENANT --second NAME --type-id TENANT
        [--manifest HASH] [--dry-run]

The export is written under `--out`; the purge's tombstone is appended to the platform audit chain
(`container.platform_audit`, TEN-075) before anything is deleted. A purge needs two
different operators and the tenant's id typed again: the command line has no `--yes`.
"""

import argparse
import asyncio
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from diucs.adapters.outbound.cache_redis.redis_cache import RedisCache
from diucs.adapters.outbound.export_files.file_storage import FileExportStorage
from diucs.adapters.outbound.graph_store.network_registry import Neo4jNetworkRegistry
from diucs.adapters.outbound.graph_store.tenant_purge import Neo4jTenantData
from diucs.adapters.outbound.graph_store.unit_of_work import neo4j_network_uow_factory
from diucs.application.actor import Actor
from diucs.application.tenancy import bind_tenant
from diucs.application.use_cases.membership import LeaveAllNetworks
from diucs.application.use_cases.network_admin import (
    CreateNetwork,
    CreateNetworkCommand,
    GovernanceRecorder,
    MapNetworkAdminGroup,
    MapNetworkAdminGroupCommand,
)
from diucs.application.use_cases.network_leave import EndProjections
from diucs.application.use_cases.tenant_offboard import (
    CompleteOffboarding,
    CompleteOffboardingCommand,
    ExportTenant,
    ExportTenantCommand,
    OffboardTenant,
)
from diucs.application.use_cases.tenant_offboarding import (
    StartOffboardingCommand,
    StartTenantOffboarding,
)
from diucs.application.use_cases.tenant_purge import PurgeTenant, PurgeTenantCommand
from diucs.application.use_cases.tenant_suspend import TenantChanged
from diucs.bootstrap.container import Container, build
from diucs.bootstrap.provisioning import AuditHeads, operator_actor
from diucs.bootstrap.settings import Settings
from diucs.domain.errors import DomainError

COMMANDS: Final = (
    "network-create",
    "network-admin-group",
    "offboard",
    "export",
    "complete-offboarding",
    "purge",
)


@dataclass(frozen=True)
class Lifecycle:
    """The use cases, on one container. The export and purge adapters depend on the command's own
    arguments (a directory, a file), so they are built per command."""

    container: Container
    network_create: CreateNetwork
    network_admin_group: MapNetworkAdminGroup
    offboard: OffboardTenant
    data: Neo4jTenantData


def build_offboard(
    container: Container, on_changed: tuple[TenantChanged, ...] = ()
) -> OffboardTenant:
    """The offboarding start of the operator's script and of its route: the memberships end
    (`LeaveAllNetworks`), then TEN-075's `StartTenantOffboarding` moves the record."""
    registry = Neo4jNetworkRegistry(container.neo4j)
    factory = container.uow_factory
    clock = container.clock
    network_factory = neo4j_network_uow_factory(container.neo4j, clock=clock)
    recorder = GovernanceRecorder(factory, network_factory, container.ids, clock)
    leave = LeaveAllNetworks(
        registry, EndProjections(network_factory, registry, clock), recorder, clock
    )
    return OffboardTenant(
        container.tenants,
        leave,
        StartTenantOffboarding(
            container.tenants, container.tenant_registry, factory, clock, on_changed
        ),
        factory,
        clock,
    )


def build_lifecycle(container: Container) -> Lifecycle:
    registry = Neo4jNetworkRegistry(container.neo4j)
    clock = container.clock
    network_factory = neo4j_network_uow_factory(container.neo4j, clock=clock)
    recorder = GovernanceRecorder(container.uow_factory, network_factory, container.ids, clock)
    return Lifecycle(
        container=container,
        network_create=CreateNetwork(
            registry, container.tenants, AuditHeads(container.neo4j), recorder, container.ids, clock
        ),
        network_admin_group=MapNetworkAdminGroup(registry, container.uow_factory, clock),
        offboard=build_offboard(container),
        data=Neo4jTenantData(container.neo4j),
    )


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="tenant_lifecycle.py",
        description="The platform operator's network creation, offboarding, export and purge.",
    )
    parser.add_argument("--operator", required=True, help="the operator's name, for the audit")
    commands = parser.add_subparsers(dest="command", required=True)

    network = commands.add_parser("network-create", help="create a network owned by a tenant")
    network.add_argument("tenant_id", help="the owner tenant")
    network.add_argument("network_id")
    network.add_argument("--name", required=True)
    network.add_argument("--agreement-reference", required=True)
    network.add_argument("--agreement-version", required=True, type=int)
    network.add_argument("--system-name", required=True)
    network.add_argument("--pathway-name", required=True)

    admins = commands.add_parser(
        "network-admin-group",
        help="map a group of the owner's directory to its network administrators",
    )
    admins.add_argument("tenant_id", help="the owner tenant")
    admins.add_argument("group", help="the directory group's object id (a GUID)")

    offboard = commands.add_parser("offboard", help="start offboarding: leave the networks")
    offboard.add_argument("tenant_id")
    offboard.add_argument("--confirm", required=True, help="the tenant's own id, typed again")

    export = commands.add_parser("export", help="write the tenant's export package")
    export.add_argument("tenant_id")
    export.add_argument("--out", required=True, type=Path)
    export.add_argument("--protected", action="store_true", help="the tenant asked for them")

    complete = commands.add_parser("complete-offboarding", help="finish offboarding")
    complete.add_argument("tenant_id")
    complete.add_argument("--out", type=Path, default=Path("."), help="where the export is held")
    complete.add_argument("--manifest", default=None, help="the export's manifest hash")
    complete.add_argument("--export-waived", action="store_true")
    complete.add_argument("--notice-waived", action="store_true")

    purge = commands.add_parser("purge", help="purge an offboarded tenant")
    purge.add_argument("tenant_id")
    purge.add_argument("--second", required=True, help="the second operator's name")
    purge.add_argument("--type-id", required=True, help="the tenant's id, typed again")
    purge.add_argument("--manifest", default=None)
    purge.add_argument("--dry-run", action="store_true")
    return parser.parse_args(list(argv))


async def run_command(
    lifecycle: Lifecycle, args: argparse.Namespace, redis_url: str = "redis://localhost:6379/0"
) -> list[str]:
    """Run one command bound to the tenant it names, and return the lines to print."""
    tenant_id: str = args.tenant_id
    actor: Actor = operator_actor(tenant_id, args.operator)
    container = lifecycle.container
    with bind_tenant(tenant_id):
        match args.command:
            case "network-create":
                made = await lifecycle.network_create.execute(
                    CreateNetworkCommand(
                        actor=actor,
                        network_id=args.network_id,
                        name=args.name,
                        agreement_reference=args.agreement_reference,
                        agreement_version=args.agreement_version,
                        system_name=args.system_name,
                        pathway_name=args.pathway_name,
                    )
                )
                return [
                    f"network {made.network_id}: "
                    + ("created, owned by the tenant" if made.created else "finished")
                ]
            case "network-admin-group":
                mapped = await lifecycle.network_admin_group.execute(
                    MapNetworkAdminGroupCommand(actor, args.group)
                )
                return [
                    "network administrators: "
                    + ("a group is mapped" if mapped.created else "the group already gave the role")
                ]
            case "offboard":
                started = await lifecycle.offboard.execute(
                    StartOffboardingCommand(actor, args.confirm)
                )
                return [
                    f"tenant {started.tenant_id}: offboarding until "
                    f"{started.notice_ends_at.isoformat()}, "
                    f"{started.memberships_ended} memberships ended"
                    + (", finished a start that had stopped" if started.resumed else "")
                ]
            case "export":
                storage = FileExportStorage(args.out)
                export = ExportTenant(
                    container.tenants,
                    lifecycle.data,
                    storage,
                    container.uow_factory,
                    container.ids,
                    container.clock,
                )
                result = await export.execute(ExportTenantCommand(actor, args.protected))
                return [
                    f"tenant {tenant_id}: package {result.package_id}, "
                    f"{len(result.files)} files, manifest {result.manifest_hash}",
                    *(f"  held back: {name} ({n})" for name, n in result.held_back.items()),
                ]
            case "complete-offboarding":
                complete = CompleteOffboarding(
                    container.tenants,
                    container.tenant_registry,
                    FileExportStorage(args.out),
                    container.uow_factory,
                    container.clock,
                )
                done = await complete.execute(
                    CompleteOffboardingCommand(
                        actor,
                        manifest_hash=args.manifest,
                        export_waived=args.export_waived,
                        notice_waived=args.notice_waived,
                    )
                )
                return [
                    f"tenant {done.tenant_id}: offboarded, "
                    f"{done.numbers_quarantined} numbers quarantined"
                ]
            case "purge":
                cache = RedisCache.from_url(redis_url)
                try:
                    purge = PurgeTenant(
                        container.tenants,
                        container.tenant_registry,
                        lifecycle.data,
                        lifecycle.data,
                        cache,
                        container.platform_audit,
                        container.clock,
                    )
                    purged = await purge.execute(
                        PurgeTenantCommand(
                            actor,
                            operator_actor(tenant_id, args.second),
                            typed_slug=args.type_id,
                            dry_run=args.dry_run,
                            export_manifest_hash=args.manifest,
                        )
                    )
                finally:
                    await cache.aclose()
                lines = [f"  {labels}: {count}" for labels, count in sorted(purged.counts.items())]
                if purged.dry_run:
                    return [f"tenant {tenant_id}: dry run, nothing deleted", *lines]
                return [
                    f"tenant {tenant_id}: purged, {purged.nodes_deleted} nodes and "
                    f"{purged.cache_names_removed} cache names deleted",
                    *lines,
                ]
    raise ValueError("unknown command")


async def _main(args: argparse.Namespace, make: Callable[[Settings], Container]) -> int:
    settings = Settings()
    container = make(settings)
    await container.startup()
    try:
        lifecycle = build_lifecycle(container)
        for line in await run_command(lifecycle, args, settings.redis_url):
            print(line)
        return 0
    except DomainError as error:
        # A refusal of the domain: its words name no tenant, number or value.
        print(f"refused: {error}", file=sys.stderr)
        return 2
    finally:
        await container.shutdown()


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    return asyncio.run(_main(args, lambda settings: build(settings)))
