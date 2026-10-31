import { decodeJwt } from 'jose';
import { DEVICES, GRANTS, REVOKED_SCREENS } from '@/test/fixtures/exchange';

// A stand-in for the back end's wall screen pairing (R15, DEC-224): `POST /screens/pairing`,
// `GET /screens/pairing/{id}` and `POST /screens`, and the lead's administration, `GET /screens` and
// `POST /screens/{id}/revoke` (W9I). It answers the shapes the route module documents
// and keeps the same rules the tests rely on: a code is the tenant's (the host's), the secret comes
// only in `X-Screen-Secret`, the device token is given once, every refusal is the one 404 and an
// expired code is `expired`. It is a stand-in, not the back end.

export const PAIRING_LIFETIME_MS = 10 * 60_000;
export const REFUSED_TEXT = 'That code is not valid or has expired.';
const CODES = ['482913', '271828', '314159', '161803', '577215'];
const DEVICE_TOKENS = Object.keys(DEVICES);

export type StandInReply = { status: number; body: unknown; headers?: Record<string, string> };

type Pairing = {
  id: string;
  host: string;
  code: string;
  secret: string;
  expiresAt: number;
  /** Set when a lead has connected the code. */
  deviceId: string | null;
  deviceToken: string | null;
  collected: boolean;
};

function outcome(status: number, code: string, text: string, headers?: Record<string, string>): StandInReply {
  return { status, body: { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code, diagnostics: text }] }, headers };
}

const refused = () => outcome(404, 'not-found', REFUSED_TEXT);
const iso = (ms: number) => new Date(ms).toISOString().replace('.000Z', 'Z');

type Screen = {
  deviceId: string;
  host: string;
  name: string;
  location: string | null;
  pairedAt: number;
  collected: boolean;
  revokedAt: number | null;
  /** The board it shows (TEN-067): its own, or the one network of the stand-in. */
  network: boolean;
  scopeVersion: number;
};

/** The one network a tenant of the stand-in may choose for a screen (the id of the network stand-in). */
export const STAND_IN_NETWORK = { id: 'net-sample', name: 'Sample network' };

function leadOf(authorization: string | null): boolean {
  const token = /^Bearer (.+)$/.exec(authorization ?? '')?.[1];
  try {
    return token !== undefined && decodeJwt(token).role === 'lead';
  } catch {
    return false;
  }
}

export class PairingStandIn {
  private pairings: Pairing[] = [];
  private screens: Screen[] = [];
  /** Revokes the stand-in has accepted, newest last. */
  readonly revokes: { host: string | null; deviceId: string; idempotencyKey: string | null; authorization: string | null }[] = [];
  private issued = 0;
  /** Connects the stand-in has accepted, newest last: what a lead sent, and the key it came with. */
  readonly connects: { host: string | null; body: unknown; idempotencyKey: string | null; authorization: string | null }[] = [];
  /** Every claim it saw: the id, whether the secret came in the header, and the host. */
  readonly claims: { id: string; secret: string | null; host: string | null }[] = [];
  readonly starts: { host: string | null }[] = [];
  /** When set, every start and claim answers this status (a throttle, an outage). */
  failWith: { status: number; headers?: Record<string, string> } | null = null;

  constructor(private readonly grants: Record<string, string[]> = GRANTS) {}

  reset() {
    this.pairings = [];
    this.screens = [];
    this.revokes.length = 0;
    REVOKED_SCREENS.clear();
    this.issued = 0;
    this.connects.length = 0;
    this.claims.length = 0;
    this.starts.length = 0;
    this.failWith = null;
  }

  /** Test control: the code a pairing is showing. */
  codeOf(id: string): string | undefined {
    return this.pairings.find((p) => p.id === id)?.code;
  }

  /** @internal The screens of the tenant a host names. */
  screensOf(host: string | null): Screen[] {
    return host === null ? [] : this.screens.filter((s) => s.host === host);
  }

  /** `GET /screens`: the lead's list for the host's tenant, in the back end's shape (routes_screens.py). */
  list(host: string | null, authorization: string | null, now: Date = new Date()): StandInReply {
    if (!leadOf(authorization)) return outcome(404, 'not-found', 'Not found.');
    const screens = this.screensOf(host).map((s) => ({
      deviceId: s.deviceId,
      name: s.name,
      location: s.location,
      state: s.revokedAt !== null ? 'revoked' : s.collected ? 'online' : 'waiting',
      status: s.revokedAt !== null ? 'revoked' : s.collected ? 'active' : 'paired-unclaimed',
      boardScope: s.network ? 'network' : 'tenant',
      networkId: s.network ? STAND_IN_NETWORK.id : null,
      networkName: s.network ? STAND_IN_NETWORK.name : null,
      networkAvailable: true,
      scopeVersion: s.scopeVersion,
      pairedAt: iso(s.pairedAt),
      lastSeenAt: s.collected && s.revokedAt === null ? iso(now.getTime()) : null,
      revokedAt: s.revokedAt === null ? null : iso(s.revokedAt),
    }));
    return { status: 200, body: { scope: 'tenant', asOf: iso(now.getTime()), screens, networks: [STAND_IN_NETWORK] }, headers: { 'Cache-Control': 'no-store' } };
  }

  /** `PUT /screens/{id}/board-scope`: the lead chooses the screen's board; the version moves when it changes (TEN-067). */
  setBoard(host: string | null, authorization: string | null, idempotencyKey: string | null, ifMatch: string | null, deviceId: string, body: unknown): StandInReply {
    if (!leadOf(authorization)) return outcome(404, 'not-found', 'Not found.');
    if (idempotencyKey === null || !/^[\x21-\x7e]{1,200}$/.test(idempotencyKey)) return outcome(400, 'required', 'Idempotency-Key is required.');
    if (ifMatch === null) return outcome(428, 'required', 'If-Match is required.');
    const screen = this.screensOf(host).find((s) => s.deviceId === deviceId && s.revokedAt === null);
    const fields = typeof body === 'object' && body !== null && !Array.isArray(body) ? (body as Record<string, unknown>) : null;
    if (screen === undefined) return outcome(404, 'not-found', 'The requested resource was not found.');
    if (fields === null || (fields.boardScope !== 'tenant' && fields.boardScope !== 'network')) return outcome(400, 'invalid', 'The request was not valid.');
    if (fields.boardScope === 'network' && fields.networkId !== STAND_IN_NETWORK.id) return outcome(404, 'not-found', 'The requested resource was not found.');
    if (ifMatch !== `W/"${screen.scopeVersion}"`) return outcome(412, 'conflict', 'The screen changed.');
    const network = fields.boardScope === 'network';
    if (screen.network !== network) {
      screen.network = network;
      screen.scopeVersion += 1;
    }
    return {
      status: 200,
      body: {
        deviceId,
        name: screen.name,
        location: screen.location,
        status: screen.collected ? 'active' : 'paired-unclaimed',
        boardScope: network ? 'network' : 'tenant',
        networkId: network ? STAND_IN_NETWORK.id : null,
        networkName: network ? STAND_IN_NETWORK.name : null,
        networkAvailable: true,
        scopeVersion: screen.scopeVersion,
      },
      headers: { 'Cache-Control': 'no-store', ETag: `W/"${screen.scopeVersion}"` },
    };
  }

  /** `GET /screens/me/board-scope`: what a screen shows, from the screen's own record (the wall token's subject). */
  ownBoardScope(deviceId: string | null): StandInReply {
    const screen = this.screens.find((s) => s.deviceId === deviceId && s.revokedAt === null);
    if (screen === undefined) return { status: 200, body: { boardScope: 'tenant', fallback: false, scopeVersion: 1 }, headers: { 'Cache-Control': 'no-store' } };
    const body = screen.network
      ? { boardScope: 'network', fallback: false, scopeVersion: screen.scopeVersion, networkName: STAND_IN_NETWORK.name }
      : { boardScope: 'tenant', fallback: false, scopeVersion: screen.scopeVersion };
    return { status: 200, body, headers: { 'Cache-Control': 'no-store' } };
  }

  /** `POST /screens/preview`: the confirm step's look at a live code (TEN-072). */
  preview(host: string | null, authorization: string | null, body: unknown, now: Date = new Date()): StandInReply {
    if (!leadOf(authorization)) return outcome(404, 'not-found', 'Not found.');
    const fields = typeof body === 'object' && body !== null && !Array.isArray(body) ? (body as Record<string, unknown>) : null;
    if (fields === null || typeof fields.code !== 'string' || Object.keys(fields).length !== 1) return outcome(400, 'invalid', 'The request was not valid.');
    const pairing = this.pairings.find((p) => p.host === host && p.code === fields.code && p.deviceToken === null && now.getTime() < p.expiresAt);
    if (pairing === undefined) return refused();
    return { status: 200, body: { firstSeenAt: iso(pairing.expiresAt - PAIRING_LIFETIME_MS), deviceClass: 'wall-display' }, headers: { 'Cache-Control': 'no-store' } };
  }

  /** `POST /screens/{id}/revoke`: ends the screen at once; the same answer again for one already ended. */
  revoke(host: string | null, authorization: string | null, idempotencyKey: string | null, deviceId: string, now: Date = new Date()): StandInReply {
    this.revokes.push({ host, deviceId, idempotencyKey, authorization });
    if (!leadOf(authorization)) return outcome(404, 'not-found', 'Not found.');
    if (idempotencyKey === null || !/^[\x21-\x7e]{1,200}$/.test(idempotencyKey)) return outcome(400, 'required', 'Idempotency-Key is required.');
    const screen = this.screensOf(host).find((s) => s.deviceId === deviceId);
    if (screen === undefined) return outcome(404, 'not-found', 'The requested resource was not found.');
    screen.revokedAt ??= now.getTime();
    REVOKED_SCREENS.add(screen.deviceId);
    return { status: 200, body: { deviceId, status: 'revoked', revokedAt: iso(screen.revokedAt) }, headers: { 'Cache-Control': 'no-store' } };
  }

  /** Test control: let a pairing's ten minutes run out. */
  expire(id: string) {
    const found = this.pairings.find((p) => p.id === id);
    if (found) found.expiresAt = 0;
  }

  private failure(): StandInReply | null {
    if (this.failWith === null) return null;
    const { status, headers } = this.failWith;
    return outcome(status, status === 429 ? 'throttled' : 'transient', 'Try again.', headers);
  }

  start(host: string | null, now: Date = new Date()): StandInReply {
    this.starts.push({ host });
    const failure = this.failure();
    if (failure) return failure;
    if (host === null || this.grants[host] === undefined) return outcome(404, 'not-found', 'Not found.');
    const n = this.issued++;
    const pairing: Pairing = {
      id: `pairing-${n + 1}`,
      host,
      code: CODES[n % CODES.length] as string,
      secret: `screen-secret-${n + 1}`,
      expiresAt: now.getTime() + PAIRING_LIFETIME_MS,
      deviceId: null,
      deviceToken: null,
      collected: false,
    };
    this.pairings.push(pairing);
    return {
      status: 201,
      body: { pairingId: pairing.id, code: pairing.code, expiresAt: new Date(pairing.expiresAt).toISOString(), screenSecret: pairing.secret },
    };
  }

  claim(host: string | null, id: string, secret: string | null, now: Date = new Date()): StandInReply {
    this.claims.push({ id, secret, host });
    const failure = this.failure();
    if (failure) return failure;
    const pairing = this.pairings.find((p) => p.id === id && p.host === host);
    if (pairing === undefined || secret === null || secret !== pairing.secret) return refused();
    if (pairing.collected) return { status: 200, body: { status: 'paired' } };
    if (now.getTime() >= pairing.expiresAt) return { status: 200, body: { status: 'expired' } };
    if (pairing.deviceToken === null) return { status: 200, body: { status: 'waiting' } };
    pairing.collected = true;
    const screen = this.screens.find((s) => s.deviceId === pairing.deviceId);
    if (screen !== undefined) screen.collected = true;
    return { status: 200, body: { status: 'paired', deviceToken: pairing.deviceToken } };
  }

  connect(host: string | null, authorization: string | null, idempotencyKey: string | null, body: unknown, now: Date = new Date()): StandInReply {
    this.connects.push({ host, body, idempotencyKey, authorization });
    const token = /^Bearer (.+)$/.exec(authorization ?? '')?.[1];
    let role: unknown;
    try {
      role = token === undefined ? undefined : decodeJwt(token).role;
    } catch {
      role = undefined;
    }
    // The role refusal of the real route is the app's generic 404, so a non-lead learns nothing about codes.
    if (role !== 'lead') return outcome(404, 'not-found', 'Not found.');
    if (idempotencyKey === null || !/^[\x21-\x7e]{1,200}$/.test(idempotencyKey)) return outcome(400, 'required', 'Idempotency-Key is required.');
    const fields = typeof body === 'object' && body !== null && !Array.isArray(body) ? (body as Record<string, unknown>) : null;
    const allowed = ['code', 'name', 'location', 'boardScope'];
    if (fields === null || Object.keys(fields).some((k) => !allowed.includes(k)) || typeof fields.code !== 'string' || typeof fields.name !== 'string') {
      return outcome(400, 'invalid', 'The request was not valid.');
    }
    if (this.failWith !== null) return this.failure() as StandInReply;
    const pairing = this.pairings.find((p) => p.code === fields.code && p.deviceToken === null && now.getTime() < p.expiresAt);
    if (pairing === undefined) return refused();
    const n = this.pairings.filter((p) => p.deviceToken !== null).length;
    pairing.deviceToken = DEVICE_TOKENS[n % DEVICE_TOKENS.length] as string;
    pairing.deviceId = DEVICES[pairing.deviceToken] as string;
    const location = typeof fields.location === 'string' ? fields.location : null;
    this.screens.push({ deviceId: pairing.deviceId, host: host as string, name: String(fields.name).trim(), location, pairedAt: now.getTime(), collected: false, revokedAt: null, network: false, scopeVersion: 1 });
    return { status: 201, body: { deviceId: pairing.deviceId, name: String(fields.name).trim(), status: 'online' } };
  }
}

export { iso };
