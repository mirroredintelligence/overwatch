// The shapes the practitioner BFF routes believe from the back end (routes_practitioner.py, DEC-1306 to
// DEC-1309). Each parser returns the answer with only the fields a screen reads, or null when the back
// end's answer is not the shape it promised: nothing unexpected is passed on and nothing is shown that was
// not checked. Times are the back end's ISO 8601 instants (UTC, whole seconds); the screens turn them into
// the tenant's clock time. No parser keeps a field it does not name, so a number, a booking id or a person
// the back end might one day add never reaches the browser. The address and contact are kept only when
// both are text, and only on an accepted visit.

export const OFFER_ID = /^[A-Za-z0-9_-]{1,64}$/;

export const SHIFT_STATUSES = ['available', 'on-a-visit', 'break', 'off-shift'] as const;
export type ShiftStatus = (typeof SHIFT_STATUSES)[number];

export const LOCATIONS = ['travel', 'never'] as const;
export type Location = (typeof LOCATIONS)[number];

export const VISIT_STATES = ['offered', 'accepted', 'on-my-way', 'arrived', 'done', 'not-reached', 'declined', 'expired', 'withdrawn'] as const;
export type VisitState = (typeof VISIT_STATES)[number];

/** The four answers of the status list on the accepted-visit screen, in screen order. */
export const PRACTITIONER_STATUSES = ['on-my-way', 'arrived', 'done', 'not-reached'] as const;
export type PractitionerStatus = (typeof PRACTITIONER_STATUSES)[number];

/** The states in which the visit is the person's to carry out (the address and contact are shown). */
export const ACTIVE_STATES: readonly VisitState[] = ['accepted', 'on-my-way', 'arrived'];

type Obj = Record<string, unknown>;

function obj(value: unknown): Obj | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? (value as Obj) : null;
}
function str(value: unknown, max = 400): string | null {
  return typeof value === 'string' && value.length > 0 && value.length <= max ? value : null;
}
function id(value: unknown): string | null {
  return typeof value === 'string' && OFFER_ID.test(value) ? value : null;
}
function instant(value: unknown): string | null {
  return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/.test(value) && !Number.isNaN(Date.parse(value)) ? value : null;
}
function oneOf<T extends string>(list: readonly T[], value: unknown): T | null {
  return typeof value === 'string' && (list as readonly string[]).includes(value) ? (value as T) : null;
}
const nullable = <T>(value: unknown, read: (v: unknown) => T | null): T | null | undefined => (value === null ? null : (read(value) ?? undefined));

export type NextVisit = { id: string; sector: string; dueBy: string | null; wantedWithin: string };
export type OfferSummary = { id: string; need: string; sector: string; wantedWithin: string; expiresAt: string };
export type RoundItem = { id: string; sector: string; state: VisitState; dueBy: string | null; wantedWithin: string };
export type Shift = {
  status: ShiftStatus | null;
  location: Location;
  visitsToday: number;
  next: NextVisit | null;
  offers: OfferSummary[];
  round: RoundItem[];
};

export function parseShift(body: unknown): Shift | null {
  const v = obj(body);
  if (v === null) return null;
  const status = nullable(v.status, (x) => oneOf(SHIFT_STATUSES, x));
  const location = oneOf(LOCATIONS, v.location);
  const visitsToday = typeof v.visitsToday === 'number' && Number.isInteger(v.visitsToday) && v.visitsToday >= 0 && v.visitsToday <= 999 ? v.visitsToday : null;
  if (status === undefined || location === null || visitsToday === null || !Array.isArray(v.offers) || !Array.isArray(v.round)) return null;

  let next: NextVisit | null = null;
  if (v.next !== null) {
    const n = obj(v.next);
    const nid = id(n?.id);
    const sector = str(n?.sector, 16);
    const dueBy = nullable(n?.dueBy, instant);
    const wantedWithin = str(n?.wantedWithin, 40);
    if (nid === null || sector === null || dueBy === undefined || wantedWithin === null) return null;
    next = { id: nid, sector, dueBy, wantedWithin };
  }

  const offers: OfferSummary[] = [];
  for (const item of v.offers) {
    const o = obj(item);
    const oid = id(o?.id);
    const need = str(o?.need, 200);
    const sector = str(o?.sector, 16);
    const wantedWithin = str(o?.wantedWithin, 40);
    const expiresAt = instant(o?.expiresAt);
    if (oid === null || need === null || sector === null || wantedWithin === null || expiresAt === null) return null;
    offers.push({ id: oid, need, sector, wantedWithin, expiresAt });
  }

  const round: RoundItem[] = [];
  for (const item of v.round) {
    const r = obj(item);
    const rid = id(r?.id);
    const sector = str(r?.sector, 16);
    const state = oneOf(VISIT_STATES, r?.state);
    const dueBy = nullable(r?.dueBy, instant);
    const wantedWithin = str(r?.wantedWithin, 40);
    if (rid === null || sector === null || state === null || dueBy === undefined || wantedWithin === null) return null;
    round.push({ id: rid, sector, state, dueBy, wantedWithin });
  }
  return { status, location, visitsToday, next, offers, round };
}

export type Visit = {
  id: string;
  reference: string;
  state: VisitState;
  need: string;
  sector: string;
  wantedWithin: string;
  expiresAt: string;
  fitsMinutes: number | null;
  etaAt: string | null;
  location: Location;
  address?: string;
  contact?: string;
};

export function parseVisit(body: unknown): Visit | null {
  const v = obj(body);
  if (v === null) return null;
  const vid = id(v.id);
  const reference = typeof v.reference === 'string' && /^\d{4}$/.test(v.reference) ? v.reference : null;
  const state = oneOf(VISIT_STATES, v.state);
  const need = str(v.need, 200);
  const sector = str(v.sector, 16);
  const wantedWithin = str(v.wantedWithin, 40);
  const expiresAt = instant(v.expiresAt);
  const fits = v.fitsMinutes === null ? null : typeof v.fitsMinutes === 'number' && Number.isInteger(v.fitsMinutes) && v.fitsMinutes >= 0 && v.fitsMinutes <= 600 ? v.fitsMinutes : undefined;
  const etaAt = nullable(v.etaAt, instant);
  const location = oneOf(LOCATIONS, v.location);
  if (vid === null || reference === null || state === null || need === null || sector === null || wantedWithin === null || expiresAt === null) return null;
  if (fits === undefined || etaAt === undefined || location === null) return null;
  const visit: Visit = { id: vid, reference, state, need, sector, wantedWithin, expiresAt, fitsMinutes: fits, etaAt, location };
  // The details go on only when the visit is active and both are text: never half of them.
  const address = str(v.address, 400);
  const contact = str(v.contact, 240);
  if (ACTIVE_STATES.includes(state) && address !== null && contact !== null) {
    visit.address = address;
    visit.contact = contact;
  }
  return visit;
}

export type Answer = { id: string; state: VisitState };

export function parseAnswer(body: unknown): Answer | null {
  const v = obj(body);
  const aid = id(v?.id);
  const state = oneOf(VISIT_STATES, v?.state);
  return aid === null || state === null ? null : { id: aid, state };
}

export type Settings = { status: ShiftStatus | null; location: Location };

export function parseSettings(body: unknown): Settings | null {
  const v = obj(body);
  const status = nullable(v?.status, (x) => oneOf(SHIFT_STATUSES, x));
  const location = oneOf(LOCATIONS, v?.location);
  return status === undefined || location === null ? null : { status, location };
}
