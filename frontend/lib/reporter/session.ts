import { createSession, type Session } from '@/lib/auth/session';

// The reporter's session in the BFF (W34, W35). It is sealed in the session cookie: the back end's
// session id is the only credential the back end has issued to a reporter, and it is not a bearer
// token (the reporter exchange is TEN-043, not built). The session lasts one shift at most.

/** [ASSUMED] DEC-660: a reporter's session lasts at most this many hours. */
export const REPORTER_SESSION_HOURS = 8;

export async function startReporterSession(input: { sessionId: string; services: string[]; device: string }): Promise<void> {
  const session: Session = {
    role: 'reporter',
    services: input.services,
    sub: input.sessionId,
    device: input.device,
    backendToken: input.sessionId,
    expiresAt: new Date(Date.now() + REPORTER_SESSION_HOURS * 60 * 60 * 1000).toISOString(),
  };
  await createSession(session);
}
