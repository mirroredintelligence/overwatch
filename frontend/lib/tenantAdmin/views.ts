import { bool, list, num, numOrNull, obj, oneOf, str, strOrNull, strings, badAnswer, type Obj } from '@/lib/operator/answers';

// What the tenant administrator's BFF routes make of the back end's answers (TEN-076, W9C-routes.md,
// `routes_tenant.py`). Server-only. Each reader keeps the fields a screen shows and drops the rest: no
// secret reference (a channel shows only that it has one), no tenant id, no opaque reference of a person or
// an account, no hash. Who wrote a draft is turned into "yours or not" with the signed-in person's own
// subject, which the back end compares the same way (an actor's practitioner id is the token's subject).

export type SettingJson = string | number | boolean | string[];

export const CONFIG_STATUSES = ['draft', 'pending-approval', 'current', 'superseded'] as const;
export type ConfigStatus = (typeof CONFIG_STATUSES)[number];

export const TICKET_STATES = ['pending', 'approved', 'refused', 'cancelled', 'opened', 'ended', 'revoked', 'expired'] as const;
export type TicketState = (typeof TICKET_STATES)[number];
export const REASON_CODES = ['security-incident', 'clinical-safety', 'service-fault', 'configuration', 'user-request', 'other'] as const;
export type ReasonCode = (typeof REASON_CODES)[number];

// ---------------------------------------------------------------- the registry

export type SettingSpec = {
  key: string;
  kind: 'int' | 'text' | 'bool' | 'time' | 'codes';
  unit: string;
  default: SettingJson | null;
  minimum: number | string | null;
  maximum: number | string | null;
  choices: number[] | null;
  allowed: string[] | null;
  safetyClass: 'clinical' | 'operational';
  scope: 'tenant' | 'network' | 'both';
  requiredForActivation: boolean;
};

function settingValue(value: unknown): SettingJson {
  if (typeof value === 'string' && value.length <= 200) return value;
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'boolean') return value;
  if (Array.isArray(value) && value.length <= 50 && value.every((item) => typeof item === 'string' && item.length <= 100)) return value as string[];
  throw badAnswer();
}

function bound(value: unknown): number | string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === 'number' || typeof value === 'string') return value;
  throw badAnswer();
}

export function parseSettings(value: unknown): { settings: SettingSpec[] } {
  const rows = list(obj(value).settings, 200).map((row) => {
    const r = obj(row);
    return {
      key: str(r.key, 64),
      kind: oneOf(r.kind, ['int', 'text', 'bool', 'time', 'codes'] as const),
      unit: str(r.unit, 40),
      default: r.default === null || r.default === undefined ? null : settingValue(r.default),
      minimum: bound(r.minimum),
      maximum: bound(r.maximum),
      choices: r.choices === null || r.choices === undefined ? null : list(r.choices, 50).map(num),
      allowed: r.allowed === null || r.allowed === undefined ? null : strings(r.allowed, 50),
      safetyClass: oneOf(r.safetyClass, ['clinical', 'operational'] as const),
      scope: oneOf(r.scope, ['tenant', 'network', 'both'] as const),
      requiredForActivation: bool(r.requiredForActivation),
    };
  });
  return { settings: rows };
}

// ---------------------------------------------------------------- the configuration

export type ConfigView = {
  version: number;
  status: ConfigStatus;
  values: Record<string, SettingJson>;
  createdAt: string;
  effectiveFrom: string | null;
  reasonCode: string;
  approvals: number;
  approvalsRequired: number;
  authoredByYou: boolean;
  approvedByYou: boolean;
  changedKeys: string[];
  clinicalKeys: string[];
  replaces: number | null;
};

function values(value: unknown): Record<string, SettingJson> {
  const raw = obj(value);
  const keys = Object.keys(raw);
  if (keys.length > 200) throw badAnswer();
  const out: Record<string, SettingJson> = {};
  for (const key of keys) out[str(key, 64)] = settingValue(raw[key]);
  return out;
}

export function parseVersion(value: unknown, you: string): ConfigView {
  const v = obj(value);
  const approvedBy = strings(v.approvedByRefs ?? [], 20);
  return {
    version: num(v.version),
    status: oneOf(v.status, CONFIG_STATUSES),
    values: values(v.values ?? {}),
    createdAt: str(v.createdAt, 40),
    effectiveFrom: strOrNull(v.effectiveFrom, 40),
    reasonCode: typeof v.reasonCode === 'string' ? v.reasonCode.slice(0, 40) : '',
    approvals: approvedBy.length,
    approvalsRequired: num(v.approvalsRequired),
    authoredByYou: str(v.createdByRef, 128) === you,
    approvedByYou: approvedBy.includes(you),
    changedKeys: strings(v.changedKeys ?? [], 100),
    clinicalKeys: strings(v.clinicalKeys ?? [], 100),
    replaces: numOrNull(v.replaces),
  };
}

export function parseVersions(value: unknown, you: string): { versions: ConfigView[] } {
  return { versions: list(obj(value).versions, 500).map((row) => parseVersion(row, you)) };
}

// ---------------------------------------------------------------- the overview

export function parseOverview(value: unknown) {
  const o = obj(value);
  const t = obj(o.tenant);
  const config = o.config === null || o.config === undefined ? null : obj(o.config);
  return {
    tenant: {
      displayName: str(t.displayName, 200),
      legalName: str(t.legalName, 300),
      organisationType: str(t.organisationType, 40),
      countryCode: str(t.countryCode, 8),
      timeZone: str(t.timeZone, 64),
      odsCode: strOrNull(t.odsCode, 16),
      status: str(t.status, 24),
      host: strOrNull(t.host, 253),
    },
    config:
      config === null
        ? null
        : {
            version: num(config.version),
            status: oneOf(config.status, CONFIG_STATUSES),
            createdAt: str(config.createdAt, 40),
            effectiveFrom: strOrNull(config.effectiveFrom, 40),
          },
    contacts: list(o.contacts, 50).map((row) => {
      const c = obj(row);
      return { kind: str(c.kind, 40), label: str(c.label, 120), value: str(c.value, 320) };
    }),
    channels: list(o.channels, 50).map((row) => {
      const c = obj(row);
      // The reference of a channel's secret is never passed on: only whether there is one.
      return {
        id: str(c.id, 64),
        kind: oneOf(c.kind, ['sms', 'email'] as const),
        provider: str(c.provider, 24),
        status: str(c.status, 24),
        senderLabel: str(c.senderLabel, 80),
        fromAddress: strOrNull(c.fromAddress, 320),
        fromDisplayName: strOrNull(c.fromDisplayName, 120),
        hasSecret: bool(c.hasSecret),
      };
    }),
    retention: list(o.retention, 50).map((row) => {
      const r = obj(row);
      return { dataClass: str(r.dataClass, 40), keepDays: numOrNull(r.keepDays), action: str(r.action, 24) };
    }),
    bindings: list(o.bindings, 50).map((row) => {
      const b = obj(row);
      return { directoryId: str(b.directoryId, 64), status: oneOf(b.status, ['pending', 'verified', 'revoked'] as const), verifiedAt: strOrNull(b.verifiedAt, 40) };
    }),
    mappings: list(o.mappings, 200).map((row) => {
      const m = obj(row);
      return { groupObjectId: str(m.groupObjectId, 64), role: str(m.role, 24), status: oneOf(m.status, ['active', 'retired'] as const) };
    }),
  };
}

// ---------------------------------------------------------------- the access log

const SNAPSHOT_VALUE = (v: unknown): v is string | number | boolean => typeof v === 'string' ? v.length <= 120 : typeof v === 'number' || typeof v === 'boolean';

function snapshotOf(value: unknown): Record<string, string | number | boolean> | null {
  if (value === null || value === undefined) return null;
  const raw = obj(value);
  const out: Record<string, string | number | boolean> = {};
  for (const key of Object.keys(raw).slice(0, 20)) if (SNAPSHOT_VALUE(raw[key])) out[key.slice(0, 40)] = raw[key];
  return out;
}

export function parseLog(value: unknown) {
  return {
    entries: list(obj(value).entries, 500).map((row) => {
      const e = obj(row);
      return {
        at: str(e.at, 40),
        useCase: str(e.useCase, 80),
        action: str(e.action, 24),
        role: oneOf(e.role, ['platform-operator', 'support'] as const),
        entityIds: strings(e.entityIds ?? [], 20),
        snapshot: snapshotOf(e.snapshot),
      };
    }),
  };
}

// ---------------------------------------------------------------- the support tickets (the administrator's side)

export function parseTicket(value: unknown) {
  const t = obj(value);
  return {
    id: str(t.id, 64),
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

export function parseTickets(value: unknown) {
  return { tickets: list(obj(value).tickets, 200).map(parseTicket) };
}

export function parseTicketApproval(value: unknown) {
  const a = obj(value);
  return { ticket: parseTicket(a.ticket), code: str(a.code, 32), codeExpiresAt: str(a.codeExpiresAt, 40) };
}

// ---------------------------------------------------------------- small answers

export function parseDraftResult(value: unknown) {
  const d = obj(value);
  return { version: num(d.version), changedKeys: strings(d.changedKeys ?? [], 100), clinicalKeys: strings(d.clinicalKeys ?? [], 100), approvalsRequired: num(d.approvalsRequired) };
}

export function parseVersionApproval(value: unknown) {
  const a = obj(value);
  return { version: num(a.version), status: oneOf(a.status, CONFIG_STATUSES), approvals: num(a.approvals), approvalsRequired: num(a.approvalsRequired) };
}

export function parseId(value: unknown) {
  return { id: str(obj(value).id, 64) };
}

export function parseStored(value: unknown) {
  return { stored: num(obj(value).stored) };
}

export type { Obj };
