import { createSession, type Session } from '@/lib/auth/session';
import { exchangeSessionToken } from './exchange';

// The reporter's session in the BFF (W34, W35, W8E). After a right PIN the back end answers its own
// PIN session id; that id is not a bearer. The BFF exchanges it for a 30-minute reporter token
// (DEC-792) and seals the TOKEN as the bearer, with the PIN session beside it so the token can be
// renewed (lib/reporter/renew.ts). The session lasts at most eight hours and a renewal never moves
// that end. Nothing here is sent to the browser.

/** [ASSUMED] DEC-660: a reporter's session lasts at most this many hours. */
export const REPORTER_SESSION_HOURS = 8;

export type ReporterSessionInput = {
  /** The back end's PIN session id. */
  sessionId: string;
  /** The tenant the back end signed the reporter in for (its answer), never a value from the request. */
  tenantId: string;
  /** The host the sign-in came to (the session is read on that host only). */
  host: string;
  device: string;
};

/**
 * Makes the session, or says it could not: `unavailable` when the back end will not give a token this
 * side believes (nobody is signed in then, and no cookie is written).
 */
export async function startReporterSession(
  input: ReporterSessionInput,
  now: Date = new Date(),
): Promise<'started' | 'unavailable'> {
  const issued = await exchangeSessionToken(
    { pinSession: input.sessionId, host: input.host, tenantId: input.tenantId, device: input.device },
    now,
  );
  if (issued.kind !== 'issued') return 'unavailable';
  const session: Session = {
    role: 'reporter',
    tenantId: input.tenantId,
    host: input.host,
    services: issued.services,
    sub: issued.sub,
    device: input.device,
    backendToken: issued.token,
    pinSession: input.sessionId,
    tokenExpiresAt: issued.tokenExpiresAt,
    expiresAt: new Date(now.getTime() + REPORTER_SESSION_HOURS * 60 * 60 * 1000).toISOString(),
  };
  await createSession(session);
  return 'started';
}
