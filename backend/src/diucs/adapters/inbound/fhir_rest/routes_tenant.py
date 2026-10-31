"""The tenant administrator's routes (TEN-075, TEN-026, TEN-065, TEN-076, TEN-084, DEC-134 item 4):
what an administrator reads and changes of their own tenant, and their side of the support-access
ticket flow.

Not FHIR: plain JSON under `/tenant`, never cached (`Cache-Control: no-store`), errors as the rest
of the API's OperationOutcome. The mount is the app root, not `/fhir`.

THE DOOR. Every route takes a tenant token (audience `diucs-api`) whose role is `tenant-admin`; any
other role, a wall screen and an operator token are refused (the role first: the non-revealing 404;
an operator token or a token the edge refuses: the 401). The tenant is the signed claim and nothing
else (`current_actor`): no path, query or body names one, so another tenant's record is not
reachable by any request. A tenant suspended read-only lets its administrator read (the edge refuses
every write); a blocked, offboarding or purged tenant is closed at the edge.

  GET  /tenant/overview                           the record, host, configuration in force,
                                                  contacts, channels (no secret references),
                                                  retention, directory binding, role mappings
  GET  /tenant/settings                           the setting registry: key, kind, bounds, class
  GET  /tenant/config/versions[/{version}]        versions newest first, each with its diff
  POST /tenant/config/drafts                      draft the next version (changes, removals)
  POST /tenant/config/versions/{version}/approval one more approval; the last one makes it current
  PUT  /tenant/contacts                           a contact, by kind
  POST /tenant/channels, PUT /tenant/channels/{id}  an email channel (the text channel is the
                                                  platform operator's)
  PUT  /tenant/retention                          the defaults, or one rule for each data class
  PUT  /tenant/directory                          bind the staff directory (pending, the operator
                                                  verifies it)
  PUT  /tenant/role-mappings                      map a directory group to a staff role
  GET  /tenant/access-log                         what the platform's own people did here
  GET  /tenant/support-tickets[/{id}]             the tickets that name this tenant
  POST /tenant/support-tickets/{id}/approval      approve: the one-time code, in this answer only
  POST /tenant/support-tickets/{id}/refusal       refuse
  DELETE /tenant/support-tickets/{id}/access      take back an approved code or end an open access

WRITES. An `Idempotency-Key` is required on every write and a repeat is answered from the 24-hour
cache, except the approval of a ticket: its answer holds the one-time code, which is never cached
(a repeat of an approval is a conflict, and the code is not issued twice).

The services are on `app.state.tenant_admin_services` (set by the process that serves the app); with
none, every route fails closed with a 500.
"""

from datetime import UTC, datetime, time
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from diucs.adapters.inbound.fhir_rest.auth import require_role
from diucs.adapters.inbound.fhir_rest.concurrency import idempotency_key, replay_or_run
from diucs.application.actor import Actor
from diucs.application.platform_services import TenantAdminServices
from diucs.application.use_cases.cross_tenant_tickets import DecideTicketCommand, TicketView
from diucs.application.use_cases.tenant_admin_views import (
    AccessLogEntry,
    ConfigVersionView,
    TenantOverview,
)
from diucs.application.use_cases.tenant_config import (
    ApproveConfigCommand,
    BindDirectoryCommand,
    DraftConfigCommand,
    MapGroupCommand,
    RecordChannelCommand,
    RecordContactCommand,
    SetRetentionCommand,
)
from diucs.domain.codes import Role
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.tenant import (
    ContactKind,
    NumberStatus,
    RetentionClass,
    TenantConfig,
)
from diucs.domain.model.tenant_policy import SettingValue
from diucs.domain.model.tenant_records import (
    ChannelKind,
    MappingStatus,
    RetentionAction,
    TenantChannel,
    TenantRetention,
)
from diucs.domain.rules.support_ticket import SupportTicket
from diucs.domain.rules.tenant_settings import (
    SETTING_SPECS,
    SettingKind,
    SettingSpec,
    spec_for,
)

router = APIRouter(prefix="/tenant")

NO_STORE: Final = {"Cache-Control": "no-store"}
TICKET_ID: Final = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
CHANNEL_ID: Final = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
TEXT_CHANNEL_MESSAGE: Final = "the text channel is set by the platform operator"
TIME_SHAPE: Final = "must be a time of day as HH:MM"

Admin = Annotated[Actor, Depends(require_role(Role.TENANT_ADMIN))]
TicketPath = Annotated[str, Path(pattern=TICKET_ID)]


# ---------------------------------------------------------------- bodies


class _Body(BaseModel):
    """A body that names anything it is not for is a bad request. None names a tenant."""

    model_config = ConfigDict(extra="forbid")


class DraftBody(_Body):
    basedOn: int = Field(ge=0, le=10**6)
    changes: dict[str, Any] = Field(default_factory=dict, max_length=64)
    removals: list[str] = Field(default_factory=list, max_length=64)
    reasonCode: str = Field(default="", max_length=40)


class ContactBody(_Body):
    kind: ContactKind
    label: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1, max_length=320)


class ChannelBody(_Body):
    kind: ChannelKind
    senderLabel: str = Field(min_length=1, max_length=80)
    fromAddress: str | None = Field(default=None, max_length=320)
    fromDisplayName: str | None = Field(default=None, max_length=120)
    secretRef: str | None = Field(default=None, max_length=128)
    status: NumberStatus = NumberStatus.ACTIVE


class RuleBody(_Body):
    dataClass: RetentionClass
    keepDays: int | None = Field(default=None, ge=1, le=100_000)
    action: RetentionAction


class RetentionBody(_Body):
    useDefaults: bool = False
    rules: list[RuleBody] = Field(default_factory=list, max_length=16)


class DirectoryBody(_Body):
    directoryId: str = Field(min_length=1, max_length=64)


class MappingBody(_Body):
    groupObjectId: str = Field(min_length=1, max_length=64)
    role: Role
    status: MappingStatus = MappingStatus.ACTIVE


# ---------------------------------------------------------------- helpers


def _services(request: Request) -> TenantAdminServices:
    # Fail closed: a missing wiring is a configuration error (a 500), never an empty answer.
    services: TenantAdminServices | None = getattr(request.app.state, "tenant_admin_services", None)
    if services is None:
        raise RuntimeError("no tenant administration services are configured for the tenant routes")
    return services


def _json(status: int, body: Any) -> Response:
    return JSONResponse(body, status_code=status, headers=NO_STORE)


def _empty() -> Response:
    return Response(status_code=204, headers=NO_STORE)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def setting_to_json(value: SettingValue) -> Any:
    """A setting as the wire holds it: a time as HH:MM, a set of codes as a sorted list."""
    if isinstance(value, time):
        return value.strftime("%H:%M")
    if isinstance(value, frozenset):
        return sorted(value)
    return value


def setting_from_json(spec: SettingSpec, raw: object) -> SettingValue:
    """A setting from the wire, by the kind of its row. The value is checked again against the
    row's bounds by the use case; this only makes the type the use case demands (its checks are by
    exact type), and refuses what cannot be made."""
    if spec.kind is SettingKind.TIME:
        if type(raw) is not str or len(raw) != 5 or raw[2] != ":":
            raise ValidationFailed(spec.key, TIME_SHAPE)
        try:
            return time(int(raw[:2]), int(raw[3:]))
        except ValueError:
            raise ValidationFailed(spec.key, TIME_SHAPE) from None
    if spec.kind is SettingKind.CODES:
        if type(raw) is not list or not all(type(item) is str for item in raw):
            raise ValidationFailed(spec.key, "must be a list of codes")
        return frozenset(raw)
    if type(raw) not in (int, str, bool):
        raise ValidationFailed(spec.key, "has the wrong type")
    return raw  # type: ignore[return-value]


def spec_to_dict(spec: SettingSpec) -> dict[str, Any]:
    return {
        "key": spec.key,
        "kind": spec.kind.value,
        "unit": spec.unit,
        "default": None if spec.default is None else setting_to_json(spec.default),
        "minimum": None if spec.minimum is None else setting_to_json(spec.minimum),
        "maximum": None if spec.maximum is None else setting_to_json(spec.maximum),
        "choices": None if spec.choices is None else sorted(spec.choices),
        "allowed": None if spec.allowed is None else sorted(spec.allowed),
        "safetyClass": spec.safety_class.value,
        "scope": spec.scope.value,
        "requiredForActivation": spec.required_for_activation,
    }


def config_to_dict(config: TenantConfig) -> dict[str, Any]:
    return {
        "version": config.version,
        "status": config.status.value,
        "values": {key: setting_to_json(value) for key, value in config.values.items()},
        "createdAt": _iso(config.created_at),
        "createdByRef": config.created_by_ref,
        "effectiveFrom": _iso(config.effective_from),
        "approvedByRefs": list(config.approved_by_refs),
        "reasonCode": config.reason_code,
    }


def version_to_dict(view: ConfigVersionView) -> dict[str, Any]:
    return {
        **config_to_dict(view.config),
        "changedKeys": list(view.changed_keys),
        "clinicalKeys": list(view.clinical_keys),
        "approvalsRequired": view.approvals_required,
        "replaces": view.replaces,
    }


def channel_to_dict(channel: TenantChannel) -> dict[str, Any]:
    """A channel without the reference of its secret: that there is one, never which."""
    return {
        "id": channel.id,
        "kind": channel.kind.value,
        "provider": channel.provider.value,
        "status": channel.status.value,
        "senderLabel": channel.sender_label,
        "accountSid": channel.account_sid,
        "fromAddress": channel.from_address,
        "fromDisplayName": channel.from_display_name,
        "hasSecret": channel.secret_ref is not None,
    }


def overview_to_dict(overview: TenantOverview) -> dict[str, Any]:
    tenant = overview.tenant
    config = overview.config
    return {
        "tenant": {
            "id": tenant.id,
            "displayName": tenant.display_name,
            "legalName": tenant.legal_name,
            "organisationType": tenant.organisation_type.value,
            "countryCode": tenant.country_code,
            "timeZone": tenant.time_zone,
            "odsCode": tenant.ods_code,
            "status": tenant.status.value,
            "host": overview.host,
        },
        "config": None if config is None else config_to_dict(config),
        "contacts": [
            {"kind": c.kind.value, "label": c.label, "value": c.value} for c in overview.contacts
        ],
        "channels": [channel_to_dict(c) for c in overview.channels],
        "retention": [
            {"dataClass": r.data_class.value, "keepDays": r.keep_days, "action": r.action.value}
            for r in overview.retention
        ],
        "bindings": [
            {
                "directoryId": b.directory_id,
                "status": b.status.value,
                "verifiedAt": _iso(b.verified_at),
            }
            for b in overview.bindings
        ],
        "mappings": [
            {
                "groupObjectId": m.group_object_id,
                "role": m.role.value,
                "status": m.status.value,
            }
            for m in overview.mappings
        ],
    }


def ticket_to_dict(view: TicketView) -> dict[str, Any]:
    """A ticket as the tenant's administrator sees it: who asked (the opaque reference of the
    support person), why, and where it stands. No hash of a code is shown."""
    ticket: SupportTicket = view.ticket
    return {
        "id": ticket.id,
        "state": view.state.value,
        "requestedByRef": ticket.requested_by_ref,
        "reasonCode": ticket.reason_code.value,
        "reason": ticket.reason,
        "reference": ticket.reference,
        "requestedAt": _iso(ticket.requested_at),
        "validUntil": _iso(ticket.valid_until),
        "decidedByRef": ticket.decided_by_ref,
        "decidedAt": _iso(ticket.decided_at),
        "openedAt": _iso(ticket.opened_at),
        "endedAt": _iso(ticket.ended_at),
        "endedBy": None if ticket.ended_by is None else ticket.ended_by.value,
        "accessId": ticket.access_id,
    }


def log_entry_to_dict(entry: AccessLogEntry) -> dict[str, Any]:
    return {
        "at": _iso(entry.at),
        "useCase": entry.use_case,
        "action": entry.action,
        "role": entry.role.value,
        "actorRef": entry.actor_ref,
        "entityIds": list(entry.entity_ids),
        "snapshot": entry.snapshot,
    }


# ---------------------------------------------------------------- reads


@router.get("/overview")
async def read_overview(request: Request, actor: Admin) -> Response:
    overview = await _services(request).reads.overview(actor)
    return _json(200, overview_to_dict(overview))


@router.get("/settings")
async def read_settings(request: Request, actor: Admin) -> Response:
    """The setting registry the drafts are made from: each key, its kind, unit, bounds, default,
    whether it is clinical (two approvers who are not its author) and whether activation needs
    it."""
    return _json(200, {"settings": [spec_to_dict(spec) for spec in SETTING_SPECS]})


@router.get("/config/versions")
async def read_versions(request: Request, actor: Admin) -> Response:
    views = await _services(request).reads.versions(actor)
    return _json(200, {"versions": [version_to_dict(view) for view in views]})


@router.get("/config/versions/{version}")
async def read_version(
    version: Annotated[int, Path(ge=1, le=10**6)], request: Request, actor: Admin
) -> Response:
    view = await _services(request).reads.version(actor, version)
    return _json(200, version_to_dict(view))


@router.get("/access-log")
async def read_access_log(
    request: Request, actor: Admin, days: Annotated[int, Query(ge=1, le=400)] = 90
) -> Response:
    entries = await _services(request).reads.access_log(actor, days)
    return _json(200, {"entries": [log_entry_to_dict(entry) for entry in entries]})


# ---------------------------------------------------------------- the configuration


@router.post("/config/drafts")
async def draft_config(body: DraftBody, request: Request, actor: Admin) -> Response:
    """Draft the next version from the one in force. `basedOn` is the version the administrator
    read (0 when there is none): a draft against a version that is no longer in force is a conflict.
    The answer says which keys changed, which are clinical and how many people must approve."""
    key = idempotency_key(request)

    async def run() -> Response:
        changes = {
            name: setting_from_json(spec_for(name), raw) for name, raw in body.changes.items()
        }
        result = await _services(request).draft.execute(
            DraftConfigCommand(
                actor=actor,
                based_on=body.basedOn,
                changes=changes,
                removals=frozenset(body.removals),
                reason_code=body.reasonCode,
            )
        )
        return _json(
            201,
            {
                "version": result.version,
                "changedKeys": list(result.diff.changed_keys),
                "clinicalKeys": list(result.diff.clinical_keys),
                "approvalsRequired": result.diff.approvals_required,
            },
        )

    return await replay_or_run(request, actor, key, run)


@router.post("/config/versions/{version}/approval")
async def approve_config(
    version: Annotated[int, Path(ge=1, le=10**6)], request: Request, actor: Admin
) -> Response:
    key = idempotency_key(request)

    async def run() -> Response:
        result = await _services(request).approve.execute(ApproveConfigCommand(actor, version))
        return _json(
            200,
            {
                "version": result.version,
                "status": result.status.value,
                "approvals": result.approvals,
                "approvalsRequired": result.approvals_required,
            },
        )

    return await replay_or_run(request, actor, key, run)


@router.put("/contacts")
async def put_contact(body: ContactBody, request: Request, actor: Admin) -> Response:
    key = idempotency_key(request)

    async def run() -> Response:
        await _services(request).contact.execute(
            RecordContactCommand(actor, body.kind, body.label, body.value)
        )
        return _empty()

    return await replay_or_run(request, actor, key, run)


def _channel_command(
    actor: Actor, body: ChannelBody, channel_id: str | None
) -> RecordChannelCommand:
    # The text channel is the platform operator's: the number, the Twilio account and the token
    # reference are the platform's business with Twilio (DEC-131 item 4).
    if body.kind is ChannelKind.SMS:
        raise ValidationFailed("kind", TEXT_CHANNEL_MESSAGE)
    return RecordChannelCommand(
        actor=actor,
        kind=body.kind,
        sender_label=body.senderLabel,
        secret_ref=body.secretRef,
        from_address=body.fromAddress,
        from_display_name=body.fromDisplayName,
        channel_id=channel_id,
        status=body.status,
    )


@router.post("/channels")
async def add_channel(body: ChannelBody, request: Request, actor: Admin) -> Response:
    key = idempotency_key(request)
    command = _channel_command(actor, body, None)

    async def run() -> Response:
        channel_id = await _services(request).channel.execute(command)
        return _json(201, {"id": channel_id})

    return await replay_or_run(request, actor, key, run)


@router.put("/channels/{channel_id}")
async def change_channel(
    channel_id: Annotated[str, Path(pattern=CHANNEL_ID)],
    body: ChannelBody,
    request: Request,
    actor: Admin,
) -> Response:
    key = idempotency_key(request)
    command = _channel_command(actor, body, channel_id)

    async def run() -> Response:
        changed = await _services(request).channel.execute(command)
        return _json(200, {"id": changed})

    return await replay_or_run(request, actor, key, run)


@router.put("/retention")
async def put_retention(body: RetentionBody, request: Request, actor: Admin) -> Response:
    key = idempotency_key(request)

    async def run() -> Response:
        rules = tuple(
            TenantRetention(rule.dataClass, rule.keepDays, rule.action) for rule in body.rules
        )
        stored = await _services(request).retention.execute(
            SetRetentionCommand(actor, rules=rules, use_defaults=body.useDefaults)
        )
        return _json(200, {"stored": stored})

    return await replay_or_run(request, actor, key, run)


@router.put("/directory")
async def put_directory(body: DirectoryBody, request: Request, actor: Admin) -> Response:
    key = idempotency_key(request)

    async def run() -> Response:
        await _services(request).bind.execute(BindDirectoryCommand(actor, body.directoryId))
        return _empty()

    return await replay_or_run(request, actor, key, run)


@router.put("/role-mappings")
async def put_role_mapping(body: MappingBody, request: Request, actor: Admin) -> Response:
    key = idempotency_key(request)

    async def run() -> Response:
        await _services(request).map_group.execute(
            MapGroupCommand(actor, body.groupObjectId, body.role, body.status)
        )
        return _empty()

    return await replay_or_run(request, actor, key, run)


# ---------------------------------------------------------------- the support-access tickets


@router.get("/support-tickets")
async def list_tickets(request: Request, actor: Admin) -> Response:
    views = await _services(request).tickets.listing.for_tenant(actor)
    return _json(200, {"tickets": [ticket_to_dict(view) for view in views]})


@router.get("/support-tickets/{ticket_id}")
async def read_ticket(ticket_id: TicketPath, request: Request, actor: Admin) -> Response:
    view = await _services(request).tickets.reading.for_tenant(actor, ticket_id)
    return _json(200, ticket_to_dict(view))


@router.post("/support-tickets/{ticket_id}/approval")
async def approve_ticket(ticket_id: TicketPath, request: Request, actor: Admin) -> Response:
    """Approve a pending ticket. The answer holds the one-time code, once: give it to the support
    person. It is valid for four hours and opens one access for an hour. It is not cached and not
    stored; if this answer is lost, revoke the ticket and the support person asks again."""
    idempotency_key(request)
    approved = await _services(request).tickets.approving.execute(
        DecideTicketCommand(actor, ticket_id)
    )
    view = await _services(request).tickets.reading.for_tenant(actor, ticket_id)
    return _json(
        200,
        {
            "ticket": ticket_to_dict(view),
            "code": approved.code,
            "codeExpiresAt": _iso(approved.code_expires_at),
        },
    )


@router.post("/support-tickets/{ticket_id}/refusal")
async def refuse_ticket(ticket_id: TicketPath, request: Request, actor: Admin) -> Response:
    key = idempotency_key(request)

    async def run() -> Response:
        services = _services(request)
        await services.tickets.refusing.execute(DecideTicketCommand(actor, ticket_id))
        return _json(
            200, ticket_to_dict(await services.tickets.reading.for_tenant(actor, ticket_id))
        )

    return await replay_or_run(request, actor, key, run)


@router.delete("/support-tickets/{ticket_id}/access")
async def revoke_ticket(ticket_id: TicketPath, request: Request, actor: Admin) -> Response:
    """Take back an approved code or end an open access at once."""
    key = idempotency_key(request)

    async def run() -> Response:
        services = _services(request)
        await services.tickets.revoking.execute(DecideTicketCommand(actor, ticket_id))
        return _json(
            200, ticket_to_dict(await services.tickets.reading.for_tenant(actor, ticket_id))
        )

    return await replay_or_run(request, actor, key, run)
