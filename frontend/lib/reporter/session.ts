import { createSession, type Session } from '@/lib/auth/session';

// The reporter's session in the BFF (W34, W35). It is sealed in the session cookie: the back end's
// session id is the only credential the back end has issued to a reporter, and it is not a bearer
// token (the reporter exchange is TEN-043, not built). The session lasts one shift at most.

/** [ASSUMED] DEC-660: a reporter's session lasts at most this many hours. */
export const REPORTER_SESSION_HOURS = 8;

export type ReporterSessionInput = {
  sessionId: string;
  /** The tenant the back end signed the reporter in for (its answer), never a value from the request. */
  tenantId: string;
  /** The host the sign-in came to (the session is read on that host only). */
  host: string;
  services: string[];
  device: string;
};

export async function startReporterSession(input: ReporterSessionInput): Promise<void> {
  const session: Session = {
    role: 'reporter',
    tenantId: input.tenantId,
    host: input.host,
    services: input.services,
    sub: input.sessionId,
    device: input.device,
    backendToken: input.sessionId,
    expiresAt: new Date(Date.now() + REPORTER_SESSION_HOURS * 60 * 60 * 1000).toISOString(),
  };
  await createSession(session);
}
