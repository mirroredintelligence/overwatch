import type { IncomingMessage, ServerResponse } from 'node:http';

// The practitioner's routes of the stand-in back end, for the browser tests (RadarPhone 1 to 4, DEC-1306 to
// DEC-1309). It answers the shapes `routes_practitioner.py` documents. Like the real back end it takes the
// person from the bearer token (any bearer is a signed-in practitioner here) and keeps the state of an offer
// in memory:
//
//   an offer is `offered` until accepted or declined; an accepted visit shows its address and contact
//   until it is done or not reached, when they are gone; a visit under way takes the status list.
//
// Each browser test uses an offer of its own (the ids below), so the tests never share state. The values are
// synthetic: no real address, name or number.

const ADDRESS = '1 Synthetic Street';
const CONTACT = 'Daughter, 07000 000000';

type State = 'offered' | 'accepted' | 'on-my-way' | 'arrived' | 'done' | 'not-reached' | 'declined' | 'withdrawn';
type Offer = { id: string; reference: string; state: State; etaAt: string | null; secondsLeft: number; need: string; sector: string; wantedWithin: string };

const OFFERS = new Map<string, Offer>();

export const PRACTITIONER_OFFERS = ['pr-accept', 'pr-decline', 'pr-taken', 'pr-axe', 'pr-status', 'pr-done', 'pr-notreached', 'pr-phone', 'pr-expiring'] as const;

function seed(id: string, over: Partial<Offer> = {}): Offer {
  return { id, reference: '4821', state: 'offered', etaAt: null, secondsLeft: 270, need: 'Fall, no injury', sector: 'DT4 8', wantedWithin: 'within 2 hrs', ...over };
}

function reset() {
  OFFERS.clear();
  for (const id of PRACTITIONER_OFFERS) OFFERS.set(id, seed(id, id === 'pr-expiring' ? { secondsLeft: 3 } : {}));
  OFFERS.set('pr-visit', seed('pr-visit', { state: 'accepted', reference: '4822' }));
  OFFERS.set('pr-visit-never', seed('pr-visit-never', { state: 'accepted', reference: '4823' }));
  OFFERS.set('pr-visit-axe', seed('pr-visit-axe', { state: 'accepted', reference: '4824' }));
}
reset();

const settings = { status: 'available' as string | null, location: 'never' as 'travel' | 'never' };
const iso = (ms: number) => new Date(ms).toISOString().replace(/\.\d{3}Z$/, 'Z');

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

const ACTIVE: State[] = ['accepted', 'on-my-way', 'arrived'];
const NOT_FOUND = { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'not-found' }] };
const CONFLICT = { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'conflict' }] };

function visitBody(offer: Offer): Json {
  const live = ACTIVE.includes(offer.state);
  const body: Json = {
    id: offer.id,
    reference: offer.reference,
    state: offer.state,
    need: offer.need,
    sector: live || offer.state === 'offered' ? offer.sector : offer.sector.split(' ')[0],
    wantedWithin: offer.wantedWithin,
    expiresAt: iso(Date.now() + offer.secondsLeft * 1000),
    fitsMinutes: null,
    etaAt: live ? offer.etaAt : null,
    location: settings.location,
  };
  if (live) {
    body.address = ADDRESS;
    body.contact = CONTACT;
  }
  return body;
}

function shiftBody(): Json {
  const open = [...OFFERS.values()];
  const offers = open.filter((o) => o.state === 'offered' && o.secondsLeft > 60);
  const round = open.filter((o) => ACTIVE.includes(o.state) || o.state === 'done');
  return {
    status: settings.status,
    location: settings.location,
    visitsToday: round.length,
    next: round[0] === undefined ? null : { id: round[0].id, sector: round[0].sector, dueBy: iso(Date.now() + 90 * 60_000), wantedWithin: round[0].wantedWithin },
    offers: offers.map((o) => ({ id: o.id, need: 'Fall, no injury', sector: o.sector, wantedWithin: o.wantedWithin, expiresAt: iso(Date.now() + o.secondsLeft * 1000) })),
    round: round.map((o) => ({ id: o.id, sector: o.sector, state: o.state, dueBy: iso(Date.now() + 90 * 60_000), wantedWithin: o.wantedWithin })),
  };
}

/** Answers the practitioner's routes and returns true; false for any other path. */
export async function handlePractitionerRoute(request: IncomingMessage, response: ServerResponse, pathname: string): Promise<boolean> {
  const method = request.method ?? 'GET';
  if (pathname === '/practitioner/__reset' && method === 'POST') {
    reset();
    settings.status = 'available';
    settings.location = 'never';
    return send(response, 200, { ok: true }), true;
  }
  if (!pathname.startsWith('/practitioner/')) return false;
  if (!/^Bearer .+/.test(String(request.headers.authorization ?? ''))) return send(response, 401, { resourceType: 'OperationOutcome', issue: [{ code: 'login' }] }), true;

  if (pathname === '/practitioner/shift' && method === 'GET') return send(response, 200, shiftBody()), true;
  if (pathname === '/practitioner/settings' && method === 'PUT') {
    const body = await readJson(request);
    if ('status' in body) settings.status = body.status === null ? null : String(body.status);
    if (typeof body.location === 'string') settings.location = body.location === 'travel' ? 'travel' : 'never';
    return send(response, 200, { status: settings.status, location: settings.location }), true;
  }
  const route = /^\/practitioner\/visits\/([^/]+)(?:\/(accept|decline|status))?$/.exec(pathname);
  if (route === null) return send(response, 404, NOT_FOUND), true;
  const offer = OFFERS.get(route[1] ?? '');
  if (offer === undefined) return send(response, 404, NOT_FOUND), true;
  const action = route[2];
  if (action === undefined && method === 'GET') return send(response, 200, visitBody(offer)), true;
  if (method !== 'POST') return send(response, 404, NOT_FOUND), true;

  const body = await readJson(request);
  if (action === 'accept' || action === 'decline') {
    // 'pr-taken' is the offer a colleague has just taken: the first accept finds it withdrawn.
    if (offer.id === 'pr-taken' && action === 'accept') {
      offer.state = 'withdrawn';
      return send(response, 409, CONFLICT), true;
    }
    if (offer.state !== 'offered') return send(response, 409, CONFLICT), true;
    offer.state = action === 'accept' ? 'accepted' : 'declined';
    return send(response, 200, { id: offer.id, state: offer.state }), true;
  }
  if (action === 'status') {
    const status = String(body.status ?? '') as State;
    if (!ACTIVE.includes(offer.state) || !['on-my-way', 'arrived', 'done', 'not-reached'].includes(status)) return send(response, 409, CONFLICT), true;
    if (body.etaMinutes !== undefined) {
      if (settings.location !== 'travel') return send(response, 400, { resourceType: 'OperationOutcome', issue: [{ code: 'invalid' }] }), true;
      offer.etaAt = iso(Date.now() + Number(body.etaMinutes) * 60_000);
    }
    if (status === 'arrived') offer.etaAt = null;
    offer.state = status;
    return send(response, 200, { id: offer.id, state: offer.state }), true;
  }
  return send(response, 404, NOT_FOUND), true;
}
