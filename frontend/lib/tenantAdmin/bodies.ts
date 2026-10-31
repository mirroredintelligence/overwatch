import { invalidRequest } from '@/lib/lead/bffInput';

// The bodies the tenant administrator's BFF routes pass to the back end, checked by shape and whitelisted
// field by field: an unknown field, one that names a tenant, a secret reference and the text channel are
// refused here with a 400 before any call. The back end checks every value again (bounds, the registry,
// the tenant's own secret store); this is the front door, not the only one.

type Obj = Record<string, unknown>;

function asObject(value: unknown): Obj {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw invalidRequest();
  return value as Obj;
}

function only(body: Obj, allowed: readonly string[]): void {
  for (const key of Object.keys(body)) if (!allowed.includes(key)) throw invalidRequest();
}

function text(value: unknown, min: number, max: number): string {
  if (typeof value !== 'string' || value.length < min || value.length > max) throw invalidRequest();
  return value;
}

function optionalText(value: unknown, max: number): string | undefined {
  if (value === undefined) return undefined;
  return text(value, 1, max);
}

function oneOf<T extends string>(value: unknown, allowed: readonly T[]): T {
  if (typeof value !== 'string' || !(allowed as readonly string[]).includes(value)) throw invalidRequest();
  return value as T;
}

const SETTING_KEY = /^[A-Za-z][A-Za-z0-9]{0,63}$/;

export function draftBody(raw: unknown): Obj {
  const body = asObject(raw);
  only(body, ['basedOn', 'changes', 'removals', 'reasonCode']);
  const { basedOn, changes = {}, removals = [], reasonCode } = body;
  if (typeof basedOn !== 'number' || !Number.isInteger(basedOn) || basedOn < 0 || basedOn > 1_000_000) throw invalidRequest();
  const changed = asObject(changes);
  const keys = Object.keys(changed);
  if (keys.length > 64) throw invalidRequest();
  for (const key of keys) {
    const value = changed[key];
    const flat = typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean';
    const codes = Array.isArray(value) && value.length <= 50 && value.every((item) => typeof item === 'string');
    if (!SETTING_KEY.test(key) || !(flat || codes)) throw invalidRequest();
  }
  if (!Array.isArray(removals) || removals.length > 64 || !removals.every((key) => typeof key === 'string' && SETTING_KEY.test(key))) throw invalidRequest();
  const out: Obj = { basedOn, changes: changed, removals };
  if (reasonCode !== undefined) out.reasonCode = text(reasonCode, 0, 40);
  return out;
}

export const CONTACT_KINDS = ['coordination-phone', 'support-email', 'shift-lead-escalation', 'clinical-safety-officer'] as const;

export function contactBody(raw: unknown): Obj {
  const body = asObject(raw);
  only(body, ['kind', 'label', 'value']);
  return { kind: oneOf(body.kind, CONTACT_KINDS), label: text(body.label, 1, 120), value: text(body.value, 1, 320) };
}

/** An email channel. The text channel is the platform operator's, and a secret reference is never sent through a browser. */
export function channelBody(raw: unknown): Obj {
  const body = asObject(raw);
  only(body, ['kind', 'senderLabel', 'fromAddress', 'fromDisplayName', 'status']);
  const out: Obj = { kind: oneOf(body.kind, ['email'] as const), senderLabel: text(body.senderLabel, 1, 80) };
  const address = optionalText(body.fromAddress, 320);
  const name = optionalText(body.fromDisplayName, 120);
  if (address !== undefined) out.fromAddress = address;
  if (name !== undefined) out.fromDisplayName = name;
  if (body.status !== undefined) out.status = oneOf(body.status, ['active', 'retired', 'quarantined'] as const);
  return out;
}

export const RETENTION_CLASSES = ['capacity-reports', 'bookings', 'case-audit', 'communications', 'telemetry-raw', 'telemetry-aggregates', 'audit-chain', 'safety-concerns'] as const;
export const RETENTION_ACTIONS = ['delete', 'summarise', 'keep'] as const;

export function retentionBody(raw: unknown): Obj {
  const body = asObject(raw);
  only(body, ['useDefaults', 'rules']);
  if (body.useDefaults === true) {
    if (body.rules !== undefined && !(Array.isArray(body.rules) && body.rules.length === 0)) throw invalidRequest();
    return { useDefaults: true };
  }
  if (!Array.isArray(body.rules) || body.rules.length === 0 || body.rules.length > 16) throw invalidRequest();
  const rules = body.rules.map((item) => {
    const rule = asObject(item);
    only(rule, ['dataClass', 'keepDays', 'action']);
    const keepDays = rule.keepDays;
    if (keepDays !== null && (typeof keepDays !== 'number' || !Number.isInteger(keepDays) || keepDays < 1 || keepDays > 100_000)) throw invalidRequest();
    return { dataClass: oneOf(rule.dataClass, RETENTION_CLASSES), keepDays, action: oneOf(rule.action, RETENTION_ACTIONS) };
  });
  return { rules };
}

export function directoryBody(raw: unknown): Obj {
  const body = asObject(raw);
  only(body, ['directoryId']);
  return { directoryId: text(body.directoryId, 1, 64) };
}

/** A directory group maps to a staff role, never to the administrator's own (the back end refuses it too). */
export const MAPPABLE_ROLES = ['advisor', 'clinical', 'lead', 'owner', 'exec', 'audit'] as const;

export function mappingBody(raw: unknown): Obj {
  const body = asObject(raw);
  only(body, ['groupObjectId', 'role', 'status']);
  const out: Obj = { groupObjectId: text(body.groupObjectId, 1, 64), role: oneOf(body.role, MAPPABLE_ROLES) };
  if (body.status !== undefined) out.status = oneOf(body.status, ['active', 'retired'] as const);
  return out;
}
