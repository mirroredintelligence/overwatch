import { createSession, type Session } from '@/lib/auth/session';
import { exchangeSessionToken } from './exchange';

// Server-only. The refresh of a reporter's token (W8E, DEC-792). The token lasts 30 minutes and
// cannot be recalled; the PIN session at the back end can. So the BFF asks again from the live PIN
// session when the token has five minutes left, or has run out, and the session ends the moment the
// back end will not give a new token.
//
//   - a renewal never moves the session's own end (eight hours, DEC-660), the person, the tenant, the
//     host, the phone or the PIN session: it replaces the token, its expiry and the services it names;
//   - the answer the back end gives is believed only for the same tenant, person and phone (the
//     exchange checks it): any other answer, and a refusal, end the session;
//   - a back end that cannot be asked ends it only once the token has run out, so a blip inside the
//     five minutes costs nothing and an outage does not leave a lapsed token in use.

/** The token is renewed when it has this long or less left. */
export const RENEW_BEFORE_MS = 5 * 60_000;

export type Renewal =
  | { kind: 'current'; session: Session }
  | { kind: 'renewed'; session: Session }
  | { kind: 'ended' };

// One exchange for the calls that find the token due together (a page makes several at once). Keyed
// by the PIN session in memory only; it is removed when the exchange settles.
const inFlight = new Map<string, Promise<Awaited<ReturnType<typeof exchangeSessionToken>>>>();

function exchangeOnce(session: Session & { pinSession: string }, now: Date) {
  const running = inFlight.get(session.pinSession);
  if (running !== undefined) return running;
  const started = exchangeSessionToken(
    { pinSession: session.pinSession, host: session.host, tenantId: session.tenantId, device: session.device ?? '', sub: session.sub },
    now,
  ).finally(() => inFlight.delete(session.pinSession));
  inFlight.set(session.pinSession, started);
  return started;
}

export async function renewIfDue(session: Session, now: Date = new Date()): Promise<Renewal> {
  if (session.pinSession === undefined || session.tokenExpiresAt === undefined) return { kind: 'current', session };
  const left = Date.parse(session.tokenExpiresAt) - now.getTime();
  if (left > RENEW_BEFORE_MS) return { kind: 'current', session };

  const result = await exchangeOnce({ ...session, pinSession: session.pinSession }, now);
  if (result.kind === 'unavailable') return left > 0 ? { kind: 'current', session } : { kind: 'ended' };
  if (result.kind !== 'issued') return { kind: 'ended' };

  const renewed: Session = {
    ...session,
    backendToken: result.token,
    tokenExpiresAt: result.tokenExpiresAt,
    services: result.services,
  };
  await createSession(renewed);
  return { kind: 'renewed', session: renewed };
}
