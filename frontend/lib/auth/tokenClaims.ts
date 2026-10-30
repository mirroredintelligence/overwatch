import { isTenantId } from './ids';

// The claims of a back-end token the back end has just issued to this server, read so the session can
// record which tenant it is for. This is NOT a verification: the front end holds no signing secret
// (TEN-043, DEC-134 item 2) and the signature is not checked here. The token came straight from the
// back end over the server-to-server call that asked for it, and the back end checks every use of it.
// What is checked here is that the answer is the shape the back end promised: a token for the staff
// audience, naming a tenant, with an expiry still ahead. Anything else is not a token this server
// will keep.

export const STAFF_AUDIENCE = 'diucs-api';
const MAX_TOKEN_LENGTH = 8192;
const MAX_SUBJECT_LENGTH = 128;
const MAX_ROLE_LENGTH = 40;
const BASE64URL = /^[A-Za-z0-9_-]+$/;

export type IssuedToken = {
  sub: string;
  role: string;
  services: string[];
  tenant: string;
  /** Seconds since the epoch. */
  exp: number;
  device?: string;
};

function parsePart(text: string): Record<string, unknown> | null {
  if (!BASE64URL.test(text)) return null;
  try {
    const value: unknown = JSON.parse(Buffer.from(text, 'base64url').toString('utf8'));
    return typeof value === 'object' && value !== null && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

function text(value: unknown, max: number): value is string {
  return typeof value === 'string' && value.length > 0 && value.length <= max;
}

/** The claims, or null when the token is not one this server will keep. */
export function readIssuedToken(token: unknown, now: Date = new Date()): IssuedToken | null {
  if (typeof token !== 'string' || token.length > MAX_TOKEN_LENGTH) return null;
  const parts = token.split('.');
  if (parts.length !== 3) return null;
  const claims = parsePart(parts[1] ?? '');
  if (claims === null) return null;

  const { sub, role, services, tenant, exp, aud, device } = claims;
  if (aud !== STAFF_AUDIENCE) return null;
  if (!isTenantId(tenant)) return null;
  if (!text(sub, MAX_SUBJECT_LENGTH) || !text(role, MAX_ROLE_LENGTH)) return null;
  if (services !== undefined && (!Array.isArray(services) || !services.every((item) => typeof item === 'string'))) return null;
  if (typeof exp !== 'number' || !Number.isInteger(exp) || exp * 1000 <= now.getTime()) return null;
  if (device !== undefined && typeof device !== 'string') return null;

  return { sub, role, services: services === undefined ? [] : [...(services as string[])], tenant, exp, device };
}
