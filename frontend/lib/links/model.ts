import { londonTime } from '@/lib/board/format';

// The capacity link's shapes and the small pure rules the link pages share. Nothing here
// reads a request or a cookie, so the same code runs on the server and in the browser.
// The shapes are the back end's as L01 built them (DEC-167 item 4). An answer that does
// not match is refused (LinkShapeError), and a page shows its "could not load" message.

export class LinkShapeError extends Error {
  constructor() {
    super('The link answer did not have the expected shape.');
    this.name = 'LinkShapeError';
  }
}

export type LinkView = {
  state: 'ok';
  purpose: string;
  serviceName: string;
  unitLabel: string;
  recordedValue: number | null;
  asOf: string | null;
  usualMin: number;
  usualMax: number;
  replyBy: string;
  nextDue: string | null;
  csrfToken: string;
};

export type LinkAnswered = {
  serviceName: string;
  value: number;
  unitLabel: string;
  recordedAt: string;
  nextDue: string | null;
};

export type LinkAnswer =
  | { action: 'confirm' }
  | { action: 'number'; value: number; confirmOutOfRange?: boolean }
  | { action: 'closed' };

export type ThanksDetail = LinkAnswered;

const MAX_FIGURE = 999;
const MAX_NAME_LENGTH = 120;
const MAX_TOKEN_TEXT = 200;

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new LinkShapeError();
  return value as Record<string, unknown>;
}

function text(value: unknown, max = MAX_NAME_LENGTH): string {
  if (typeof value !== 'string' || value.length === 0 || value.length > max) throw new LinkShapeError();
  return value;
}

function instant(value: unknown): string {
  if (typeof value !== 'string' || Number.isNaN(Date.parse(value))) throw new LinkShapeError();
  return value;
}

function instantOrNull(value: unknown): string | null {
  return value === null ? null : instant(value);
}

function whole(value: unknown, min: number, max: number): number {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < min || value > max) {
    throw new LinkShapeError();
  }
  return value;
}

/** The open link's page: only the fields the page reads. Anything else in the answer is dropped. */
export function parseLinkView(value: unknown): LinkView {
  const body = record(value);
  if (body.state !== 'ok') throw new LinkShapeError();
  return {
    state: 'ok',
    purpose: text(body.purpose, MAX_TOKEN_TEXT),
    serviceName: text(body.serviceName),
    unitLabel: text(body.unitLabel),
    recordedValue: body.recordedValue === null ? null : whole(body.recordedValue, 0, MAX_FIGURE),
    asOf: instantOrNull(body.asOf),
    usualMin: whole(body.usualMin, 0, MAX_FIGURE),
    usualMax: whole(body.usualMax, 0, MAX_FIGURE),
    replyBy: text(body.replyBy, MAX_TOKEN_TEXT),
    nextDue: instantOrNull(body.nextDue),
    csrfToken: text(body.csrfToken, MAX_TOKEN_TEXT),
  };
}

/** The answer a recorded figure gets back: what the thank-you page says. */
export function parseLinkAnswered(value: unknown): LinkAnswered {
  const body = record(value);
  return {
    serviceName: text(body.serviceName),
    value: whole(body.value, 0, MAX_FIGURE),
    unitLabel: text(body.unitLabel),
    recordedAt: instant(body.recordedAt),
    nextDue: instantOrNull(body.nextDue),
  };
}

/**
 * Splits a unit as the back end sends it into its noun and its time window, so the page can
 * ask "How many referrals can you take in the next 2 hrs?" and say "referrals" on its own.
 */
export function splitUnitLabel(unitLabel: string): { noun: string; window: string } {
  const at = unitLabel.indexOf(' in ');
  if (at < 0) return { noun: unitLabel, window: '' };
  return { noun: unitLabel.slice(0, at), window: unitLabel.slice(at + 1) };
}

/** An instant as London local time, "HH:MM". */
export function londonHm(instant: string): string {
  return londonTime(instant);
}

const THANKS = {
  service: 'serviceName',
  value: 'value',
  unit: 'unit',
  at: 'at',
  next: 'next',
} as const;

/** The thank-you address carries the answer the page shows. It is never the token. */
export function thanksQuery(answered: LinkAnswered): URLSearchParams {
  const query = new URLSearchParams({
    [THANKS.service]: answered.serviceName,
    [THANKS.value]: String(answered.value),
    [THANKS.unit]: answered.unitLabel,
    [THANKS.at]: answered.recordedAt,
  });
  if (answered.nextDue !== null) query.set(THANKS.next, answered.nextDue);
  return query;
}

/** The answer the thank-you page shows, or null when the address does not carry a whole one. */
export function parseThanks(params: URLSearchParams): ThanksDetail | null {
  try {
    const value = params.get(THANKS.value);
    if (value === null || !/^\d{1,3}$/.test(value)) return null;
    const next = params.get(THANKS.next);
    return parseLinkAnswered({
      serviceName: params.get(THANKS.service),
      value: Number(value),
      unitLabel: params.get(THANKS.unit),
      recordedAt: params.get(THANKS.at),
      nextDue: next === null ? null : next,
    });
  } catch {
    return null;
  }
}
