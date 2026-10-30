import { readToken, sessionEnd } from '@/lib/auth/exchange';
import { isTenantId } from '@/lib/auth/ids';
import { normaliseHost } from '@/lib/auth/host';
import type { Session } from '@/lib/auth/session';

// The applicant's session, made from the back end's answer to a right code (W23, DEC-900, DEC-901).
// Pure: the answer, the host the request came to, the device the code was checked on, and the clock.
// The tenant is the one the back end bound from the host and answered as `tenant`; the person is the
// token's subject; the token is the session's back-end token. A session is made only when every one
// of those is one this side can vouch for, and the caller writes nothing otherwise (fail closed).

export type SignInInput = {
  /** The Host the request was addressed to, as the request gives it. Null when it gave none. */
  host: string | null;
  /** The device the code was checked on (the pending cookie's). */
  deviceId: string;
  now: Date;
};

export function reporterSessionFor(answer: unknown, input: SignInInput): Session | null {
  if (typeof answer !== 'object' || answer === null || Array.isArray(answer)) return null;
  const body = answer as Record<string, unknown>;
  if (body.role !== 'reporter') return null;
  if (!isTenantId(body.tenant)) return null;
  const host = normaliseHost(input.host);
  if (host === null) return null;
  if (typeof body.token !== 'string') return null;
  const claims = readToken(body.token);
  if (claims === null) return null;
  if (typeof body.expiresAt !== 'string') return null;
  const expiresAt = sessionEnd(body.expiresAt, claims.expiresAtMs, input.now);
  if (expiresAt === null) return null;
  const services = typeof body.serviceId === 'string' ? [body.serviceId] : [];
  return {
    role: 'reporter',
    tenantId: body.tenant,
    host,
    services,
    sub: claims.sub,
    device: input.deviceId,
    backendToken: body.token,
    expiresAt,
  };
}
