import type { IncomingMessage, ServerResponse } from 'node:http';
import { fakeBackendToken } from '@/test/backendToken';
import { tenantOfHost } from '@/test/fixtures/exchange';

// The reporter's routes of the stand-in back end, for the browser tests (W7B A2, W7C; W8E). It answers
// the shapes the real route modules document: the invitation, the set-up codes, the channel, the PIN
// sign-in with its PIN session, the exchange of that session for a 30-minute reporter token, the services
// and a prompt, a report, the set-up summary and the push key. Sample values only. Like the real back end
// it takes the tenant from the Host and the reporter from the bearer token, and refuses any other.

export const GOOD_INVITATION = 'E2eReporterInvitation01';
export const EXPIRED_INVITATION = 'E2eExpiredInvitation001';
export const GOOD_CODE = '482913';
export const GOOD_PIN = '246810';
const PIN_SESSION = 'e2e-pin-session-0123456789abcdefghijklmnopqrs';
const PERSON = 'prac-e2e0123456789abcdef0123456789ab';
const SERVICE = 'svc-e2e-west';
// The stand-in has no device store: it remembers the phone of the last PIN sign-in, which the token names.
let lastDevice = 'D'.repeat(22);

type Json = Record<string, unknown>;

function send(response: ServerResponse, status: number, body: Json) {
  response.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
  response.end(JSON.stringify(body));
}

function readJson(request: IncomingMessage): Promise<Json> {
  return new Promise((resolve) => {
    let text = '';
    request.on('data', (chunk: Buffer) => (text += chunk.toString()));
    request.on('end', () => {
      try {
        const parsed = JSON.parse(text) as unknown;
        resolve(typeof parsed === 'object' && parsed !== null ? (parsed as Json) : {});
      } catch {
        resolve({});
      }
    });
  });
}

const iso = (ms: number) => new Date(ms).toISOString().replace(/\.\d{3}Z$/, 'Z');

function tokenFor(host: string, device: string) {
  const now = new Date();
  const expires = new Date(now.getTime() + 30 * 60_000);
  const token = fakeBackendToken({ sub: PERSON, role: 'reporter', services: [SERVICE], tenant: tenantOfHost(host), device, exp: Math.floor(expires.getTime() / 1000) }, now);
  return { token, expiresAt: iso(expires.getTime()), role: 'reporter' };
}

/** Answers the reporter's routes and returns true; false for any other path. */
export async function handleReporterRoute(request: IncomingMessage, response: ServerResponse, pathname: string): Promise<boolean> {
  const host = String(request.headers.host ?? '');
  const method = request.method ?? 'GET';
  let match: RegExpExecArray | null;

  if ((match = /^\/invitations\/([^/]+)$/.exec(pathname)) && method === 'GET') {
    if (match[1] !== GOOD_INVITATION) return send(response, 410, { state: 'expired' }), true;
    return send(response, 200, { state: 'valid', service: 'UCR West', role: 'reporter', maskedPhone: '07xxx xxx456', expiresAt: iso(Date.now() + 48 * 3_600_000) }), true;
  }
  if ((match = /^\/identity\/invitations\/([^/]+)\/code$/.exec(pathname)) && method === 'POST') {
    return send(response, 202, { accepted: true, resendAfterSeconds: 60 }), true;
  }
  if ((match = /^\/identity\/invitations\/([^/]+)\/code\/verify$/.exec(pathname)) && method === 'POST') {
    const body = await readJson(request);
    if (match[1] === GOOD_INVITATION && body.code === GOOD_CODE) return send(response, 200, { verified: true }), true;
    return send(response, 400, { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'invalid', diagnostics: 'That code is not right' }], triesLeft: 4 }), true;
  }
  if (pathname === '/identity/channel' && method === 'POST') {
    const body = await readJson(request);
    return send(response, 200, { channel: body.channel }), true;
  }
  if (pathname === '/identity/pin' && method === 'POST') return send(response, 200, { pinSet: true }), true;
  if (pathname === '/identity/pin/verify' && method === 'POST') {
    const body = await readJson(request);
    if (body.pin !== GOOD_PIN) {
      return send(response, 403, { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'forbidden', diagnostics: 'That PIN is not right' }], triesLeft: 4 }), true;
    }
    lastDevice = String(body.deviceId ?? lastDevice);
    return send(response, 200, { signedIn: true, sessionId: PIN_SESSION, tenant: tenantOfHost(host), role: 'reporter', services: [SERVICE] }), true;
  }
  if (pathname === '/identity/session-token' && method === 'POST') {
    const body = await readJson(request);
    if (body.sessionId !== PIN_SESSION) return send(response, 404, { resourceType: 'OperationOutcome', issue: [{ code: 'not-found' }] }), true;
    // The device the session was made on: the stand-in remembers the last PIN sign-in's phone as the one claim it can check.
    return send(response, 200, tokenFor(host, lastDevice)), true;
  }
  if (pathname === '/public/push-key' && method === 'GET') return send(response, 200, { publicKey: 'BE2eVapidPublicKey_0123456789-abcdefghijklmnopqrstuvwxyz' }), true;

  const bearer = /^Bearer (.+)$/.exec(String(request.headers.authorization ?? ''))?.[1];
  if (pathname.startsWith('/reporter/') || pathname === '/identity/push-subscription') {
    if (bearer === undefined) return send(response, 401, { resourceType: 'OperationOutcome', issue: [{ code: 'login' }] }), true;
    if (pathname === '/reporter/services') {
      return send(response, 200, { services: [{ id: SERVICE, name: 'UCR West', state: 'due', recordedValue: 3, unitLabel: 'referrals in the next 2 hrs', at: iso(Date.now() - 3_600_000), nextDue: iso(Date.now() + 3_600_000), pendingAcceptance: false }] }), true;
    }
    if (pathname === `/reporter/services/${SERVICE}/prompt`) {
      return send(response, 200, { service: 'UCR West', unitLabel: 'referrals in the next 2 hrs', recordedValue: 3, asOf: iso(Date.now() - 3_600_000), low: 0, high: 8, replyBy: iso(Date.now() + 1_800_000), nextDue: iso(Date.now() + 3_600_000) }), true;
    }
    if (pathname === `/reporter/services/${SERVICE}/report` && method === 'POST') {
      return send(response, 200, { result: 'recorded', serviceName: 'UCR West', value: 3, recordedAt: iso(Date.now()), nextDue: iso(Date.now() + 3_600_000) }), true;
    }
    if (pathname === `/reporter/services/${SERVICE}/history`) return send(response, 200, { items: [{ at: iso(Date.now()), value: 3, kind: 'confirm' }] }), true;
    if (pathname === '/reporter/setup-summary') {
      return send(response, 200, { service: 'UCR West', contactBy: 'app', maskedPhone: '07xxx xxx456', nextUpdateDue: iso(Date.now() + 3_600_000), textCodeInDays: 30 }), true;
    }
    if (pathname === '/identity/push-subscription') return send(response, 200, { saved: true }), true;
    return send(response, 404, { resourceType: 'OperationOutcome', issue: [{ code: 'not-found' }] }), true;
  }
  return false;
}
