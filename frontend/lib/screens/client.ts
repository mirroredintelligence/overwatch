import { formatCode } from './model';

// The browser's calls to the BFF's screen routes (the wall display's pairing, the lead's connect).
// Each answer is checked before a page uses it, and each failure is one of a few kinds: the pages
// have words of their own for them and never show anything the BFF or the back end said, except the
// BFF's own fixed message for a field that was wrong.

export type ScreenFailureKind = 'not-found' | 'throttled' | 'unavailable' | 'unauthorised' | 'invalid';
export type ScreenField = 'code' | 'name' | 'location';

export class ScreenClientError extends Error {
  kind: ScreenFailureKind;
  /** How long the BFF asked to wait, in milliseconds, for a throttle that said. */
  retryAfterMs: number | null = null;
  /** For `invalid`: the field that was wrong, when it is one the form has. */
  field?: ScreenField;
  /** For `invalid`: the BFF's own words for it. */
  detail?: string;

  constructor(kind: ScreenFailureKind) {
    super('The screen request failed.');
    this.name = 'ScreenClientError';
    this.kind = kind;
  }
}

const BASE = '/api/bff/screens';
const MAX_WAIT_MS = 600_000; // the back end's pairing window is ten minutes
const PAIRING_ID = /^[A-Za-z0-9_-]{1,64}$/;
const CODE = /^[0-9]{6}$/;
const FIELDS: readonly string[] = ['code', 'name', 'location'];
const DETAIL_MAX = 200;

async function send(url: string, init: RequestInit = {}): Promise<Response> {
  try {
    return await fetch(url, { cache: 'no-store', credentials: 'same-origin', ...init });
  } catch {
    throw new ScreenClientError('unavailable');
  }
}

async function bodyOf(response: Response): Promise<Record<string, unknown>> {
  try {
    const body = (await response.json()) as unknown;
    return typeof body === 'object' && body !== null && !Array.isArray(body) ? (body as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

function waitOf(response: Response): number | null {
  const header = response.headers.get('Retry-After');
  if (header === null || !/^\d{1,6}$/.test(header)) return null;
  return Math.min(Number(header) * 1000, MAX_WAIT_MS);
}

function failureOf(response: Response): ScreenClientError {
  if (response.status === 404) return new ScreenClientError('not-found');
  if (response.status === 429) return Object.assign(new ScreenClientError('throttled'), { retryAfterMs: waitOf(response) });
  return new ScreenClientError('unavailable');
}

/** A screen that holds a device cookie asks for a new wall session. Done when it has one. */
export async function renewSession(signal?: AbortSignal): Promise<void> {
  const response = await send(`${BASE}/session`, { method: 'POST', signal });
  if (!response.ok) throw failureOf(response);
  if ((await bodyOf(response)).status !== 'paired') throw new ScreenClientError('unavailable');
}

export type StartedPairing = { pairingId: string; code: string; expiresAt: string };

/** The display asks for a code. The secret that goes with it stays in the BFF's cookie. */
export async function startPairing(signal?: AbortSignal): Promise<StartedPairing> {
  const response = await send(`${BASE}/pairing`, { method: 'POST', signal });
  if (response.status !== 201) throw failureOf(response);
  const { pairingId, code, expiresAt } = await bodyOf(response);
  if (typeof pairingId !== 'string' || !PAIRING_ID.test(pairingId)) throw new ScreenClientError('unavailable');
  if (typeof code !== 'string' || !CODE.test(code) || formatCode(code) === '') throw new ScreenClientError('unavailable');
  if (typeof expiresAt !== 'string' || Number.isNaN(Date.parse(expiresAt))) throw new ScreenClientError('unavailable');
  return { pairingId, code, expiresAt };
}

export type PairingStatus = 'waiting' | 'paired' | 'expired' | 'connecting';
const STATUSES: readonly string[] = ['waiting', 'paired', 'expired', 'connecting'];

export async function pollPairing(pairingId: string, signal?: AbortSignal): Promise<PairingStatus> {
  const response = await send(`${BASE}/pairing/${encodeURIComponent(pairingId)}`, { method: 'GET', signal });
  if (!response.ok) throw failureOf(response);
  const { status } = await bodyOf(response);
  if (typeof status !== 'string' || !STATUSES.includes(status)) throw new ScreenClientError('unavailable');
  return status as PairingStatus;
}

export type ConnectInput = { code: string; name: string; location: string | null };
export type Connected = { name: string; status: 'online'; connectedAt: string };

/** The lead connects a screen. The session's CSRF token is read first and sent as the header. */
export async function connectScreen(input: ConnectInput, signal?: AbortSignal): Promise<Connected> {
  const session = await send('/api/bff/session', { method: 'GET', signal });
  if (session.status === 401 || session.status === 403) throw new ScreenClientError('unauthorised');
  const csrfToken = session.ok ? (await bodyOf(session)).csrfToken : undefined;
  if (typeof csrfToken !== 'string' || csrfToken === '') throw new ScreenClientError('unavailable');

  const body: Record<string, string> = { code: input.code, name: input.name };
  if (input.location !== null) body.location = input.location;
  const response = await send(BASE, {
    method: 'POST',
    signal,
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
    body: JSON.stringify(body),
  });

  if (response.status === 201) {
    const { name, status, connectedAt } = await bodyOf(response);
    if (status !== 'online' || typeof name !== 'string' || typeof connectedAt !== 'string' || Number.isNaN(Date.parse(connectedAt))) {
      throw new ScreenClientError('unavailable');
    }
    return { name, status, connectedAt };
  }
  if (response.status === 400 || response.status === 422) {
    const { field, message } = await bodyOf(response);
    const error = new ScreenClientError('invalid');
    if (typeof field === 'string' && FIELDS.includes(field)) error.field = field as ScreenField;
    if (typeof message === 'string' && message.length <= DETAIL_MAX) error.detail = message;
    throw error;
  }
  if (response.status === 401 || response.status === 403) throw new ScreenClientError('unauthorised');
  throw failureOf(response);
}
