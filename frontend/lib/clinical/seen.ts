// What the advisor saw when they asked, and the way to reach the advisor, as the back end sends them to the
// clinician who holds the request (W9G: `GET /clinical/requests/{id}/seen` and `/advisor-contact`).
//
// Capacity only: the back end sends each service's name, status, figure, how old the figure was and, for a
// service that was not suitable, why. It sends no postcode, district, identifier of a service or a person, and
// this reader keeps none whatever it is sent. A display that cannot be read whole is refused whole: half a
// display read as the whole of it is the risk.

export const SEEN_STATES = ['shown', 'none', 'unreadable'] as const;
export type SeenState = (typeof SEEN_STATES)[number];
const SHOWN_AS = ['option', 'not-suitable'] as const;
const STATUSES = ['accepting', 'limited', 'not-accepting', 'over-capacity', 'not-updated', 'out-of-hours'] as const;

export type SeenLine = {
  service: string;
  shownAs: (typeof SHOWN_AS)[number];
  status: (typeof STATUSES)[number];
  statusText: string;
  /** What the service could take, "+n" when it was over capacity, or null when it had no figure. */
  figure: string | null;
  /** "9 min old". */
  age: string;
  /** The figure was over the stale limit when the advisor saw it. */
  stale: boolean;
  why: string | null;
  criteriaVersion: number | null;
};

export type Seen = {
  state: SeenState;
  /** ISO 8601 UTC; null unless a display was read. */
  shownAt: string | null;
  options: number;
  noneFitted: boolean;
  lines: SeenLine[];
};

type Fields = Record<string, unknown>;

function object(value: unknown, what: string): Fields {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new Error(`${what} is not an object`);
  return value as Fields;
}

function oneOf<T extends string>(list: readonly T[], value: unknown, what: string): T {
  if (typeof value !== 'string' || !(list as readonly string[]).includes(value)) throw new Error(`${what} is not known`);
  return value as T;
}

function text(value: unknown, what: string): string {
  if (typeof value !== 'string' || value === '') throw new Error(`${what} is missing`);
  return value;
}

function textOrNull(value: unknown, what: string): string | null {
  if (value === null) return null;
  return text(value, what);
}

function flag(value: unknown, what: string): boolean {
  if (typeof value !== 'boolean') throw new Error(`${what} is not true or false`);
  return value;
}

function lineFrom(value: unknown): SeenLine {
  const line = object(value, 'a line');
  const version = line.criteriaVersion;
  if (version !== null && !(typeof version === 'number' && Number.isInteger(version) && version >= 1)) throw new Error('criteria version is not a version');
  return {
    service: text(line.service, 'service'),
    shownAs: oneOf(SHOWN_AS, line.shownAs, 'shown as'),
    status: oneOf(STATUSES, line.status, 'status'),
    statusText: text(line.statusText, 'status text'),
    figure: textOrNull(line.figure, 'figure'),
    age: text(line.age, 'age'),
    stale: flag(line.stale, 'stale'),
    why: textOrNull(line.why, 'why'),
    criteriaVersion: version as number | null,
  };
}

export function seenFromJson(body: unknown): Seen {
  const seen = object(body, 'what the advisor saw');
  const state = oneOf(SEEN_STATES, seen.state, 'state');
  if (!Array.isArray(seen.lines)) throw new Error('lines are not a list');
  if (typeof seen.options !== 'number' || !Number.isInteger(seen.options) || seen.options < 0) throw new Error('options is not a count');
  const noneFitted = flag(seen.noneFitted, 'none fitted');
  const shownAt = textOrNull(seen.shownAt, 'shown at');
  if (state === 'shown' && shownAt === null) throw new Error('a shown display has a time');
  if (state !== 'shown' && (shownAt !== null || seen.lines.length > 0)) throw new Error('a display that is not shown has no time and no lines');
  return { state, shownAt, options: seen.options, noneFitted, lines: seen.lines.map(lineFrom) };
}

const lower = (value: string) => value.charAt(0).toLowerCase() + value.slice(1);

/**
 * One line as the advisor saw it: "UCR West: accepting, 4, 9 min old". A figure that was old, and a service
 * that was not suitable, are said in words as well, so neither is colour or position alone.
 */
export function seenLineText(line: SeenLine): string {
  const figure = line.figure ?? (line.shownAs === 'option' ? 'no figure' : null);
  const base = [lower(line.statusText), figure, line.age].filter((part): part is string => part !== null).join(', ');
  const sentences = [`${line.service}: ${base}`];
  if (line.stale) sentences.push('Over 2 hrs old.');
  if (line.shownAs === 'not-suitable') {
    const reason = line.why !== null && line.why !== line.statusText ? `: ${lower(line.why)}` : '';
    sentences.push(`Not suitable${reason}.`);
  }
  // The first part has no full stop of its own: join it to the sentences with one.
  return sentences.length === 1 ? sentences[0]! : `${sentences[0]}. ${sentences.slice(1).join(' ')}`;
}

export const CONTACT_VIAS = ['work-phone', 'advisor-line'] as const;
export type ContactVia = (typeof CONTACT_VIAS)[number];
export type AdvisorContact = { via: ContactVia | null; phone: string | null; name: string | null };

// A phone number as the back end holds one: digits, spaces and a leading plus, nothing else.
const PHONE = /^\+?[0-9][0-9 ]{4,20}[0-9]$/;

export function advisorContactFromJson(body: unknown): AdvisorContact {
  const contact = object(body, 'the contact');
  const available = flag(contact.available, 'available');
  if (!available) {
    if (contact.via !== null || contact.phone !== null || contact.name !== null) throw new Error('no number carries nothing else');
    return { via: null, phone: null, name: null };
  }
  const via = oneOf(CONTACT_VIAS, contact.via, 'way');
  const phone = text(contact.phone, 'phone');
  if (!PHONE.test(phone)) throw new Error('phone is not a phone number');
  return { via, phone, name: textOrNull(contact.name, 'name') };
}
