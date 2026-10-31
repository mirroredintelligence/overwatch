import { badAnswer, bool, list, num, numOrNull, obj, oneOf, str, strOrNull, strings } from './answers';

// What the operator console's BFF routes make of the back end's `/platform` answers (TEN-083, W9C-routes.md,
// `routes_platform.py`). Server-only. Each reader keeps the fields a screen shows and drops the rest: no
// reference of a number's auth token (only whether it has one), no epoch, no access id. A shape that is not
// the one expected is a failure (a fixed 502), never a half page.

export const TENANT_STATUSES = ['provisioning', 'active', 'suspended', 'offboarding', 'offboarded', 'purged'] as const;
export const TICKET_STATES = ['pending', 'approved', 'refused', 'cancelled', 'opened', 'ended', 'revoked', 'expired'] as const;
export const REASON_CODES = ['security-incident', 'clinical-safety', 'service-fault', 'configuration', 'user-request', 'other'] as const;

/** The list. A support person's row is id, name and status only: the rest is null whatever the back end sent. */
export function parseTenantList(value: unknown, role: 'platform-operator' | 'support') {
  return {
    tenants: list(obj(value).tenants, 2000).map((row) => {
      const t = obj(row);
      const full = role === 'platform-operator';
      return {
        id: str(t.id, 64),
        displayName: str(t.displayName, 200),
        status: oneOf(t.status, TENANT_STATUSES),
        organisationType: full ? strOrNull(t.organisationType, 40) : null,
        host: full ? strOrNull(t.host, 253) : null,
        activatedAt: full ? strOrNull(t.activatedAt, 40) : null,
      };
    }),
  };
}

export function parseTenantDetail(value: unknown) {
  const d = obj(value);
  const t = obj(d.tenant);
  const refs = obj(t.references ?? {});
  const activation = d.activation === null || d.activation === undefined ? null : obj(d.activation);
  return {
    tenant: {
      id: str(t.id, 64),
      displayName: str(t.displayName, 200),
      legalName: str(t.legalName, 300),
      organisationType: str(t.organisationType, 40),
      countryCode: str(t.countryCode, 8),
      timeZone: str(t.timeZone, 64),
      odsCode: strOrNull(t.odsCode, 16),
      status: oneOf(t.status, TENANT_STATUSES),
      createdAt: str(t.createdAt, 40),
      activatedAt: strOrNull(t.activatedAt, 40),
      suspendedAt: strOrNull(t.suspendedAt, 40),
      suspendMode: strOrNull(t.suspendMode, 24),
      suspendReason: strOrNull(t.suspendReason, 40),
      offboardingStartedAt: strOrNull(t.offboardingStartedAt, 40),
      references: { dsa: strOrNull(refs.dsa, 128), dpia: strOrNull(refs.dpia, 128), dcb0160: strOrNull(refs.dcb0160, 128) },
    },
    host: strOrNull(d.host, 253),
    directoryId: strOrNull(d.directoryId, 64),
    numbers: list(d.numbers, 50).map((row) => {
      const n = obj(row);
      // The reference of a number's auth token is not passed on: only whether there is one.
      return {
        e164: str(n.e164, 20),
        accountSid: str(n.accountSid, 64),
        status: str(n.status, 24),
        testedAt: strOrNull(n.testedAt, 40),
        quarantineUntil: strOrNull(n.quarantineUntil, 40),
        hasSecret: bool(n.hasSecret),
      };
    }),
    activation: activation === null ? null : { ready: bool(activation.ready), blockers: strings(activation.blockers ?? [], 50) },
  };
}

export function parseRecorded(value: unknown) {
  return { recorded: bool(obj(value).recorded) };
}

export function parseCreated(value: unknown) {
  const v = obj(value);
  return { created: bool(v.created), recorded: bool(v.recorded) };
}

export function parseReferences(value: unknown) {
  const v = obj(value);
  return { references: strings(v.references ?? [], 10), recorded: bool(v.recorded) };
}

export function parseInvitation(value: unknown) {
  const v = obj(value);
  return { expiresAt: str(v.expiresAt, 40), recorded: bool(v.recorded) };
}

export function parseSuspension(value: unknown) {
  const v = obj(value);
  return { mode: oneOf(v.mode, ['read-only', 'blocked'] as const), recorded: bool(v.recorded) };
}

export function parseResumption(value: unknown) {
  const v = obj(value);
  return { servicesPrompted: num(v.servicesPrompted), servicesAnnounced: num(v.servicesAnnounced), resumedAgain: bool(v.resumedAgain), recorded: bool(v.recorded) };
}

export function parseOffboarding(value: unknown) {
  const v = obj(value);
  return { startedAt: str(v.startedAt, 40), noticeEndsAt: str(v.noticeEndsAt, 40), recorded: bool(v.recorded) };
}

function snapshot(value: unknown): Record<string, string | number | boolean> | null {
  if (value === null || value === undefined) return null;
  const raw = obj(value);
  const out: Record<string, string | number | boolean> = {};
  for (const key of Object.keys(raw).slice(0, 20)) {
    const v = raw[key];
    if ((typeof v === 'string' && v.length <= 120) || typeof v === 'number' || typeof v === 'boolean') out[key.slice(0, 40)] = v;
  }
  return out;
}

export function parseAudit(value: unknown) {
  const v = obj(value);
  return {
    entries: list(v.entries, 500).map((row) => {
      const e = obj(row);
      return {
        seq: num(e.seq),
        action: str(e.action, 64),
        principalRef: str(e.principalRef, 128),
        tenantId: strOrNull(e.tenantId, 64),
        accessId: strOrNull(e.accessId, 64),
        snapshot: snapshot(e.snapshot),
        at: str(e.at, 40),
      };
    }),
    next: numOrNull(v.next),
  };
}

export function parseIntact(value: unknown) {
  return { intact: bool(obj(value).intact) };
}

/** A ticket as the support person sees it. The access id is not passed on: the console never needs it. */
export function parseSupportTicket(value: unknown) {
  const t = obj(value);
  return {
    id: str(t.id, 64),
    tenantId: str(t.tenantId, 64),
    state: oneOf(t.state, TICKET_STATES),
    reasonCode: oneOf(t.reasonCode, REASON_CODES),
    reason: str(t.reason, 300),
    reference: strOrNull(t.reference, 64),
    requestedAt: str(t.requestedAt, 40),
    validUntil: str(t.validUntil, 40),
    decidedAt: strOrNull(t.decidedAt, 40),
    openedAt: strOrNull(t.openedAt, 40),
    endedAt: strOrNull(t.endedAt, 40),
    endedBy: t.endedBy === null || t.endedBy === undefined ? null : oneOf(t.endedBy, ['support', 'tenant-admin'] as const),
  };
}

export function parseSupportTickets(value: unknown) {
  return { tickets: list(obj(value).tickets, 200).map(parseSupportTicket) };
}

export function parseAccessOpened(value: unknown) {
  const v = obj(value);
  return { ticket: parseSupportTicket(v.ticket), access: { expiresAt: str(obj(v.access).expiresAt, 40) } };
}

export { badAnswer };
