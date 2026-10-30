"""The platform operator's provisioning, wired (TEN-028, DEC-503): `scripts/provision_tenant.py`.

The composition root of the operator's tenant lifecycle: the use cases of `tenant_admin.py` and
`tenant_access.py` built on one container, and the command line that runs them. It is in bootstrap,
the one layer that may name the registry adapter, bind a tenant and read the settings. Nothing here
holds a rule.

Each command acts on one tenant. The tenant is the one named on the command line, bound for the
command and for nothing else (`bind_tenant`), and the actor is the platform operator named with
`--operator`, of that tenant: an operator has no standing in any scope, only the one they act on,
and no data access (DEC-134 item 4). The script prints what happened in fixed words. It prints no
token, number, address or invitation link, and it needs the platform's secret store for the one
command that hashes a mobile (`invite`): a process that has none refuses it, closed.

    provision_tenant.py --operator NAME create TENANT --display-name X --legal-name Y --type icb
    provision_tenant.py --operator NAME host TENANT HOST
    provision_tenant.py --operator NAME number TENANT E164 ACCOUNT-SID --label SENDER-LABEL
    provision_tenant.py --operator NAME number-tested TENANT E164
    provision_tenant.py --operator NAME references TENANT [--dsa REF] [--dpia REF] [--dcb0160 REF]
    provision_tenant.py --operator NAME verify-directory TENANT DIRECTORY-ID
    provision_tenant.py --operator NAME invite TENANT MOBILE
    provision_tenant.py --operator NAME activate TENANT
    provision_tenant.py --operator NAME status TENANT
    provision_tenant.py --operator NAME suspend TENANT --mode blocked --reason security-incident
    provision_tenant.py --operator NAME resume TENANT

A suspension takes effect within the edge's cache interval (60 seconds, TEN-073): this process is
not the serving one, so it cannot make the serving process forget the tenant; the interval is the
bound.
"""

import argparse
import asyncio
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final

from diucs.adapters.outbound.audit_neo4j.audit_log import ensure_audit_head
from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.application.actor import Actor
from diucs.application.ports.outbound.identity import HmacPhoneHasher
from diucs.application.ports.outbound.tokens import LinkTokenRepository, LinkTokenService
from diucs.application.tenancy import bind_tenant
from diucs.application.tenant_settings import DirectoryHostUrl, DirectoryZones
from diucs.application.use_cases.tenant_access import InviteTenantAdmin, InviteTenantAdminCommand
from diucs.application.use_cases.tenant_admin import (
    ActivateTenant,
    ActivateTenantCommand,
    CreateTenant,
    CreateTenantCommand,
    MarkNumberTested,
    MarkNumberTestedCommand,
    RecordNumberCommand,
    RecordReferencesCommand,
    RecordTenantNumber,
    RecordTenantReferences,
    SetHostCommand,
    SetTenantHost,
    VerifyDirectoryCommand,
    VerifyEntraBinding,
)
from diucs.application.use_cases.tenant_suspend import (
    ResumeTenant,
    ResumeTenantCommand,
    SuspendTenant,
    SuspendTenantCommand,
)
from diucs.bootstrap.container import Container, build
from diucs.bootstrap.settings import Settings
from diucs.domain.codes import Role
from diucs.domain.errors import DomainError
from diucs.domain.model.tenant import OrganisationType, SuspendMode, SuspendReason, TenantStatus

OPERATOR_CHANNEL: Final = "script"
COMMANDS: Final = (
    "create",
    "host",
    "number",
    "number-tested",
    "references",
    "verify-directory",
    "invite",
    "activate",
    "status",
    "suspend",
    "resume",
)


class AuditHeads:
    """The `ScopeProvisioner` over the one connection: the bound scope's audit chain head."""

    def __init__(self, connection: Neo4jConnection) -> None:
        self._connection = connection

    async def ensure_audit_head(self) -> None:
        await ensure_audit_head(self._connection.driver)


@dataclass(frozen=True)
class Provisioning:
    """The operator's use cases, on one container."""

    create: CreateTenant
    number: RecordTenantNumber
    tested: MarkNumberTested
    host: SetTenantHost
    references: RecordTenantReferences
    directory: VerifyEntraBinding
    invite: InviteTenantAdmin
    activate: ActivateTenant
    suspend: SuspendTenant
    resume: ResumeTenant
    container: Container


def build_provisioning(container: Container) -> Provisioning:
    """The use cases of `tenant_admin.py` and `tenant_access.py` over the container's directory,
    registry, units of work, clock, ids and secrets."""
    tenants = container.tenants
    registry = container.tenant_registry
    factory = container.uow_factory
    clock = container.clock

    def tokens(repo: LinkTokenRepository) -> LinkTokenService:
        return LinkTokenService(repo, container.secrets, clock)

    return Provisioning(
        create=CreateTenant(tenants, registry, AuditHeads(container.neo4j), factory, clock),
        number=RecordTenantNumber(tenants, registry, factory, clock),
        tested=MarkNumberTested(tenants, registry, factory, clock),
        host=SetTenantHost(tenants, registry, factory, clock),
        references=RecordTenantReferences(tenants, registry, factory, clock),
        directory=VerifyEntraBinding(tenants, registry, factory, clock),
        invite=InviteTenantAdmin(
            tenants,
            factory,
            tokens,
            HmacPhoneHasher(container.secrets),
            container.sealer,
            clock,
            container.ids,
            DirectoryHostUrl(tenants),
        ),
        activate=ActivateTenant(
            tenants, registry, factory, container.ids, clock, container.area_districts_for
        ),
        suspend=SuspendTenant(tenants, registry, factory, clock),
        resume=ResumeTenant(
            tenants, registry, factory, container.ids, clock, DirectoryZones(tenants)
        ),
        container=container,
    )


def operator_actor(tenant_id: str, operator: str) -> Actor:
    """The platform operator, acting on one tenant: no service, no device, no standing elsewhere."""
    return Actor(
        role=Role.PLATFORM_OPERATOR,
        practitioner_id=operator,
        device_id=None,
        channel=OPERATOR_CHANNEL,
        service_ids=frozenset(),
        tenant_id=tenant_id,
    )


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="provision_tenant.py", description="The platform operator's tenant provisioning."
    )
    parser.add_argument(
        "--operator", required=True, help="the operator's name, for the audit trail"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create", help="create a tenant in provisioning")
    create.add_argument("tenant_id")
    create.add_argument("--display-name", required=True)
    create.add_argument("--legal-name", required=True)
    create.add_argument("--type", required=True, choices=[t.value for t in OrganisationType])
    create.add_argument("--country", default="GB")
    create.add_argument("--ods-code", default=None)

    host = commands.add_parser("host", help="set the tenant's host")
    host.add_argument("tenant_id")
    host.add_argument("host")

    number = commands.add_parser("number", help="record the tenant's text number")
    number.add_argument("tenant_id")
    number.add_argument("e164")
    number.add_argument("account_sid")
    number.add_argument("--label", required=True, help="the sender label")

    tested = commands.add_parser("number-tested", help="record a delivered test text")
    tested.add_argument("tenant_id")
    tested.add_argument("e164")

    references = commands.add_parser("references", help="record the references asserted")
    references.add_argument("tenant_id")
    references.add_argument("--dsa", default=None)
    references.add_argument("--dpia", default=None)
    references.add_argument("--dcb0160", default=None)

    directory = commands.add_parser("verify-directory", help="verify the bound Entra directory")
    directory.add_argument("tenant_id")
    directory.add_argument("directory_id")

    invite = commands.add_parser("invite", help="invite the tenant's first administrator")
    invite.add_argument("tenant_id")
    invite.add_argument("mobile")

    activate = commands.add_parser("activate", help="activate the tenant")
    activate.add_argument("tenant_id")

    status = commands.add_parser("status", help="show the tenant's state and what is missing")
    status.add_argument("tenant_id")

    suspend = commands.add_parser("suspend", help="suspend an active tenant")
    suspend.add_argument("tenant_id")
    suspend.add_argument("--mode", required=True, choices=[m.value for m in SuspendMode])
    suspend.add_argument("--reason", required=True, choices=[r.value for r in SuspendReason])

    resume = commands.add_parser("resume", help="resume a suspended tenant")
    resume.add_argument("tenant_id")
    return parser.parse_args(list(argv))


async def run_command(provisioning: Provisioning, args: argparse.Namespace) -> list[str]:
    """Run one command bound to the tenant it names, and return the lines to print. Every line is
    fixed words and ids: no number, address, token or link."""
    tenant_id: str = args.tenant_id
    actor = operator_actor(tenant_id, args.operator)
    with bind_tenant(tenant_id):
        match args.command:
            case "create":
                created = await provisioning.create.execute(
                    CreateTenantCommand(
                        actor=actor,
                        tenant_id=tenant_id,
                        display_name=args.display_name,
                        legal_name=args.legal_name,
                        organisation_type=OrganisationType(args.type),
                        country_code=args.country,
                        ods_code=args.ods_code,
                    )
                )
                return [
                    f"tenant {created.tenant_id}: "
                    + ("created in provisioning" if created.created else "scope finished")
                ]
            case "host":
                await provisioning.host.execute(SetHostCommand(actor, args.host))
                return [f"tenant {tenant_id}: host set"]
            case "number":
                channel = await provisioning.number.execute(
                    RecordNumberCommand(actor, args.e164, args.account_sid, args.label)
                )
                return [f"tenant {tenant_id}: number recorded as channel {channel}"]
            case "number-tested":
                await provisioning.tested.execute(MarkNumberTestedCommand(actor, args.e164))
                return [f"tenant {tenant_id}: number marked as tested"]
            case "references":
                recorded = await provisioning.references.execute(
                    RecordReferencesCommand(
                        actor,
                        dsa_ref=args.dsa,
                        dpia_ref=args.dpia,
                        dcb0160_ref=args.dcb0160,
                    )
                )
                return [f"tenant {tenant_id}: recorded {', '.join(recorded)}"]
            case "verify-directory":
                await provisioning.directory.execute(
                    VerifyDirectoryCommand(actor, args.directory_id)
                )
                return [f"tenant {tenant_id}: directory verified"]
            case "invite":
                invited = await provisioning.invite.execute(
                    InviteTenantAdminCommand(actor, args.mobile)
                )
                return [
                    f"tenant {tenant_id}: invitation queued, valid until "
                    f"{invited.expires_at.isoformat()}"
                ]
            case "activate":
                done = await provisioning.activate.execute(ActivateTenantCommand(actor))
                return [f"tenant {done.tenant_id}: active, epoch {done.epoch}"]
            case "status":
                return await _status(provisioning, actor, tenant_id)
            case "suspend":
                suspended = await provisioning.suspend.execute(
                    SuspendTenantCommand(actor, SuspendMode(args.mode), SuspendReason(args.reason))
                )
                return [
                    f"tenant {suspended.tenant_id}: suspended {suspended.mode.value}, "
                    f"epoch {suspended.epoch}"
                ]
            case "resume":
                resumed = await provisioning.resume.execute(ResumeTenantCommand(actor))
                return [
                    f"tenant {resumed.tenant_id}: active again, epoch {resumed.epoch}, "
                    f"{resumed.services_prompted} services prompted"
                ]
    raise ValueError("unknown command")


async def _status(provisioning: Provisioning, actor: Actor, tenant_id: str) -> list[str]:
    """The state, and what activation still waits for, in the blockers' fixed words."""
    tenant = await provisioning.container.tenants.get(tenant_id)
    if tenant is None:
        return [f"tenant {tenant_id}: not found"]
    lines = [f"tenant {tenant_id}: {tenant.status.value}, epoch {tenant.epoch}"]
    if tenant.status is TenantStatus.PROVISIONING:
        assessment = await provisioning.activate.assess(actor)
        lines.extend(f"  missing: {item}" for item in assessment.blockers)
    return lines


async def _main(args: argparse.Namespace, make: Callable[[Settings], Container]) -> int:
    container = make(Settings())
    await container.startup()
    try:
        provisioning = build_provisioning(container)
        for line in await run_command(provisioning, args):
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
