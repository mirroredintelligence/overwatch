import { invalidRequest } from '@/lib/lead/bffInput';
import { directoryBody, MAPPABLE_ROLES } from '@/lib/tenantAdmin/bodies';
import { isUkMobile } from '@/lib/forms/ukMobile';
import { REASON_CODES } from './views';

// The bodies the operator console's BFF routes pass to the back end, checked by shape and whitelisted field
// by field. No body names a tenant (the tenant is the path's); an unknown field, one that names a tenant, a
// number that is not E.164, a mobile that is not a UK mobile and a reason that is not a plain sentence are
// refused here with a 400 before any call. The back end checks every value again: this is the front door.

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
function oneOf<T extends string>(value: unknown, allowed: readonly T[]): T {
  if (typeof value !== 'string' || !(allowed as readonly string[]).includes(value)) throw invalidRequest();
  return value as T;
}

export const ORGANISATION_TYPES = ['nhs-trust', 'icb', 'gp-practice', 'local-authority', 'voluntary-independent', 'other'] as const;
export const SUSPENSION_MODES = ['read-only', 'blocked'] as const;
export const SUSPENSION_REASONS = ['security-incident', 'information-governance', 'clinical-safety', 'contract', 'operator-request'] as const;

function odsRecordBody(raw: unknown): Obj {
  const record = asObject(raw);
  if (!Array.isArray(record.roles) || record.roles.length > 20) throw invalidRequest();
  if (!Array.isArray(record.links) || record.links.length > 50) throw invalidRequest();
  return {
    code: text(record.code, 1, 8),
    name: text(record.name, 1, 120),
    status: text(record.status, 1, 40),
    postcode: record.postcode === null || record.postcode === undefined ? null : text(record.postcode, 1, 16),
    primaryRole: record.primaryRole === null || record.primaryRole === undefined ? null : text(record.primaryRole, 1, 20),
    roles: record.roles.map((r: unknown) => {
      const role = asObject(r);
      return { id: text(role.id, 1, 20), name: text(role.name, 1, 120), primary: role.primary === true };
    }),
    links: record.links.map((l: unknown) => {
      const link = asObject(l);
      return { relationship: text(link.relationship, 1, 10), code: text(link.code, 1, 8), name: text(link.name, 1, 120), role: typeof link.role === 'string' ? text(link.role, 0, 20) : '' };
    }),
    lastChangedAt: record.lastChangedAt === null || record.lastChangedAt === undefined ? null : text(record.lastChangedAt, 1, 40),
  };
}

export function createTenantBody(raw: unknown): Obj {
  const body = asObject(raw);
  only(body, ['displayName', 'legalName', 'organisationType', 'countryCode', 'timeZone', 'odsCode', 'odsRecord', 'directoryId', 'roleMappings']);
  const out: Obj = {
    displayName: text(body.displayName, 1, 200),
    legalName: text(body.legalName, 1, 300),
    organisationType: oneOf(body.organisationType, ORGANISATION_TYPES),
  };
  if (body.countryCode !== undefined) out.countryCode = text(body.countryCode, 2, 2);
  if (body.timeZone !== undefined) out.timeZone = text(body.timeZone, 1, 64);
  if (body.odsCode !== undefined) out.odsCode = text(body.odsCode, 1, 16);
  // The NHS record the operator confirmed (DEC-1314). The back end checks every value again.
  if (body.odsRecord !== undefined) out.odsRecord = odsRecordBody(body.odsRecord);
  // The directory the tenant's staff will sign in through (bound as waiting; the operator verifies it later)
  // and the groups of it that give a role. A group is never given the administrator's role: the list has none.
  if (body.directoryId !== undefined) out.directoryId = directoryBody({ directoryId: body.directoryId }).directoryId;
  if (body.roleMappings !== undefined) {
    if (!Array.isArray(body.roleMappings) || body.roleMappings.length > 12) throw invalidRequest();
    out.roleMappings = body.roleMappings.map((raw: unknown) => {
      const mapping = asObject(raw);
      only(mapping, ['groupObjectId', 'role']);
      return { groupObjectId: text(mapping.groupObjectId, 1, 64), role: oneOf(mapping.role, MAPPABLE_ROLES) };
    });
  }
  return out;
}

const HOST = /^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$/;
export function hostBody(raw: unknown): Obj {
  const body = asObject(raw);
  only(body, ['host']);
  const host = text(body.host, 3, 253);
  if (!HOST.test(host)) throw invalidRequest();
  return { host };
}

const E164 = /^\+[1-9]\d{6,14}$/;
function e164(value: unknown): string {
  const v = text(value, 8, 16);
  if (!E164.test(v)) throw invalidRequest();
  return v;
}
export function numberBody(raw: unknown): Obj {
  const body = asObject(raw);
  only(body, ['e164', 'accountSid', 'senderLabel']);
  return { e164: e164(body.e164), accountSid: text(body.accountSid, 1, 64), senderLabel: text(body.senderLabel, 1, 80) };
}
export function testedBody(raw: unknown): Obj {
  const body = asObject(raw);
  only(body, ['e164']);
  return { e164: e164(body.e164) };
}

export function referencesBody(raw: unknown): Obj {
  const body = asObject(raw);
  only(body, ['dsaRef', 'dpiaRef', 'dcb0160Ref']);
  const out: Obj = {};
  for (const key of ['dsaRef', 'dpiaRef', 'dcb0160Ref']) if (body[key] !== undefined) out[key] = text(body[key], 1, 128);
  if (Object.keys(out).length === 0) throw invalidRequest();
  return out;
}

export const verificationBody = directoryBody;

export function invitationBody(raw: unknown): Obj {
  const body = asObject(raw);
  only(body, ['mobile']);
  const mobile = text(body.mobile, 8, 24);
  if (!isUkMobile(mobile)) throw invalidRequest();
  return { mobile };
}

export function suspensionBody(raw: unknown): Obj {
  const body = asObject(raw);
  only(body, ['mode', 'reason']);
  return { mode: oneOf(body.mode, SUSPENSION_MODES), reason: oneOf(body.reason, SUSPENSION_REASONS) };
}

/** The operator types the tenant's own id; the back end gets it as `confirmTenantId`. It must be the path's. */
export function offboardingBody(raw: unknown, tenantId: string): Obj {
  const body = asObject(raw);
  only(body, ['confirm']);
  if (body.confirm !== tenantId) throw invalidRequest();
  return { confirmTenantId: tenantId };
}

const REASON_TEXT = /^[A-Za-z0-9 .,'&()+-]{10,200}$/;
export function ticketRequestBody(raw: unknown): Obj {
  const body = asObject(raw);
  only(body, ['reasonCode', 'reason', 'reference']);
  const reason = text(body.reason, 10, 200);
  if (!REASON_TEXT.test(reason) || (reason.match(/\d/g) ?? []).length > 6) throw invalidRequest();
  const out: Obj = { reasonCode: oneOf(body.reasonCode, REASON_CODES), reason };
  if (body.reference !== undefined) {
    const reference = text(body.reference, 1, 32);
    if (!/^[A-Za-z0-9-]{1,32}$/.test(reference)) throw invalidRequest();
    out.reference = reference;
  }
  return out;
}

export function codeBody(raw: unknown): Obj {
  const body = asObject(raw);
  only(body, ['code']);
  const code = text(body.code, 9, 9);
  if (!/^[A-Z0-9]{4}-[A-Z0-9]{4}$/.test(code)) throw invalidRequest();
  return { code };
}
