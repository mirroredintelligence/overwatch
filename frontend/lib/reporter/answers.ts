// The shapes the reporter's BFF routes believe from the back end (W7C routes_reporter.py, W8E). Each
// parser returns the answer with only the fields a screen reads, or null when the back end's answer is
// not the shape it promised: nothing unexpected is passed on, and nothing is shown that was not
// checked. Times are the back end's ISO 8601 instants (UTC, whole seconds); the screens turn them into
// the tenant's clock time. No parser keeps a field it does not name, so a number, a Task id or a person
// the back end might one day add never reaches the browser.

export const SERVICE_ID = /^[A-Za-z0-9_-]{1,64}$/;
export const BOOKING_REFERENCE = /^\d{4}$/;
export const IDEMPOTENCY_KEY = /^[A-Za-z0-9-]{8,64}$/;

type Obj = Record<string, unknown>;

function obj(value: unknown): Obj | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? (value as Obj) : null;
}
function str(value: unknown, max = 200): string | null {
  return typeof value === 'string' && value.length > 0 && value.length <= max ? value : null;
}
function int(value: unknown, min = 0, max = 999): number | null {
  return typeof value === 'number' && Number.isInteger(value) && value >= min && value <= max ? value : null;
}
function instant(value: unknown): string | null {
  return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/.test(value) && !Number.isNaN(Date.parse(value)) ? value : null;
}
const nullable = <T>(value: unknown, read: (v: unknown) => T | null): T | null | undefined =>
  value === null ? null : (read(value) ?? undefined);

export const CHANNELS = ['app', 'text', 'email'] as const;
export type ChannelWord = (typeof CHANNELS)[number];
const channelWord = (v: unknown): ChannelWord | null => (CHANNELS as readonly string[]).includes(v as string) ? (v as ChannelWord) : null;

export type ServiceRowOut = {
  id: string;
  name: string;
  state: 'confirmed' | 'due' | 'paused';
  recordedValue: number | null;
  unitLabel: string;
  at: string | null;
  nextDue: string | null;
  pendingAcceptance: boolean;
  letter?: string;
  replyBy?: string;
};

export function parseServices(body: unknown): { services: ServiceRowOut[] } | null {
  const list = obj(body)?.services;
  if (!Array.isArray(list)) return null;
  const services: ServiceRowOut[] = [];
  for (const item of list) {
    const row = obj(item);
    if (row === null) return null;
    const id = typeof row.id === 'string' && SERVICE_ID.test(row.id) ? row.id : null;
    const name = str(row.name);
    const recordedValue = nullable(row.recordedValue, (v) => int(v));
    const unitLabel = str(row.unitLabel);
    const at = nullable(row.at, instant);
    const nextDue = nullable(row.nextDue, instant);
    const state = row.state;
    if (id === null || name === null || unitLabel === null) return null;
    if (recordedValue === undefined || at === undefined || nextDue === undefined) return null;
    if (state !== 'confirmed' && state !== 'due' && state !== 'paused') return null;
    if (typeof row.pendingAcceptance !== 'boolean') return null;
    const out: ServiceRowOut = { id, name, state, recordedValue, unitLabel, at, nextDue, pendingAcceptance: row.pendingAcceptance };
    if (row.letter !== undefined) {
      const letter = str(row.letter, 3);
      if (letter === null) return null;
      out.letter = letter;
    }
    if (row.replyBy !== undefined) {
      const replyBy = instant(row.replyBy);
      if (replyBy === null) return null;
      out.replyBy = replyBy;
    }
    services.push(out);
  }
  return { services };
}

export type PromptOut = {
  service: string;
  unitLabel: string;
  recordedValue: number | null;
  asOf: string | null;
  low: number;
  high: number;
  replyBy: string | null;
  nextDue: string | null;
};

export function parsePrompt(body: unknown): PromptOut | null {
  const v = obj(body);
  if (v === null) return null;
  const service = str(v.service);
  const unitLabel = str(v.unitLabel);
  const recordedValue = nullable(v.recordedValue, (x) => int(x));
  const asOf = nullable(v.asOf, instant);
  const replyBy = nullable(v.replyBy, instant);
  const nextDue = nullable(v.nextDue, instant);
  const low = int(v.low);
  const high = int(v.high);
  if (service === null || unitLabel === null || low === null || high === null) return null;
  if (recordedValue === undefined || asOf === undefined || replyBy === undefined || nextDue === undefined) return null;
  return { service, unitLabel, recordedValue, asOf, low, high, replyBy, nextDue };
}

export function parseHistory(body: unknown): { items: { at: string; value: number; kind: string }[] } | null {
  const list = obj(body)?.items;
  if (!Array.isArray(list)) return null;
  const items: { at: string; value: number; kind: string }[] = [];
  for (const entry of list) {
    const item = obj(entry);
    const at = instant(item?.at);
    const value = int(item?.value);
    const kind = str(item?.kind, 16);
    if (at === null || value === null || kind === null) return null;
    items.push({ at, value, kind });
  }
  return { items };
}

export type SettingsOut = { channel: ChannelWord; maskedPhone: string; maskedCover: string | null; reverifyInDays: number; otherDevices: number };

export function parseSettings(body: unknown): SettingsOut | null {
  const v = obj(body);
  if (v === null) return null;
  const channel = channelWord(v.channel);
  const maskedPhone = str(v.maskedPhone, 32);
  const maskedCover = nullable(v.maskedCover, (x) => str(x, 32));
  const reverifyInDays = int(v.reverifyInDays, 0, 3650);
  const otherDevices = int(v.otherDevices, 0, 1000);
  if (channel === null || maskedPhone === null || maskedCover === undefined || reverifyInDays === null || otherDevices === null) return null;
  return { channel, maskedPhone, maskedCover, reverifyInDays, otherDevices };
}

export type SummaryOut = { service: string; contactBy: ChannelWord; maskedPhone: string; nextUpdateDue: string | null; textCodeInDays: number };

export function parseSummary(body: unknown): SummaryOut | null {
  const v = obj(body);
  if (v === null) return null;
  const service = str(v.service);
  const contactBy = channelWord(v.contactBy);
  const maskedPhone = str(v.maskedPhone, 32);
  const nextUpdateDue = nullable(v.nextUpdateDue, instant);
  const textCodeInDays = int(v.textCodeInDays, 0, 3650);
  if (service === null || contactBy === null || maskedPhone === null || nextUpdateDue === undefined || textCodeInDays === null) return null;
  return { service, contactBy, maskedPhone, nextUpdateDue, textCodeInDays };
}

export type BookingOut = {
  reference: string;
  service: string;
  ageBand: string | null;
  need: string;
  urgency: string | null;
  replyBy: string;
  status: 'requested' | 'confirmed' | 'declined' | 'expired';
  bookingStatus: string;
  multiService: boolean;
  spoaPhone: string | null;
  confirmedAt?: string;
};

export function parseBooking(body: unknown): BookingOut | null {
  const v = obj(body);
  if (v === null) return null;
  const reference = typeof v.reference === 'string' && BOOKING_REFERENCE.test(v.reference) ? v.reference : null;
  const service = str(v.service);
  const ageBand = nullable(v.ageBand, (x) => str(x, 40));
  const need = str(v.need, 400);
  const urgency = nullable(v.urgency, (x) => str(x, 80));
  const replyBy = instant(v.replyBy);
  const bookingStatus = str(v.bookingStatus, 32);
  const spoaPhone = nullable(v.spoaPhone, (x) => str(x, 32));
  const status = v.status;
  if (reference === null || service === null || need === null || replyBy === null || bookingStatus === null) return null;
  if (ageBand === undefined || urgency === undefined || spoaPhone === undefined) return null;
  if (status !== 'requested' && status !== 'confirmed' && status !== 'declined' && status !== 'expired') return null;
  if (typeof v.multiService !== 'boolean') return null;
  const out: BookingOut = { reference, service, ageBand, need, urgency, replyBy, status, bookingStatus, multiService: v.multiService, spoaPhone };
  if (v.confirmedAt !== undefined) {
    const confirmedAt = instant(v.confirmedAt);
    if (confirmedAt === null) return null;
    out.confirmedAt = confirmedAt;
  }
  return out;
}

export type ReportAnswer =
  | { result: 'recorded'; serviceName: string; value: number; recordedAt: string; nextDue: string | null }
  | { result: 'outOfRange'; serviceName: string; value: number; low: number; high: number }
  | { result: 'sendNumber'; serviceName: string; reason?: string }
  | { result: 'confirmLimit'; serviceName: string };

export function parseReport(body: unknown): ReportAnswer | null {
  const v = obj(body);
  if (v === null) return null;
  const serviceName = str(v.serviceName);
  if (serviceName === null) return null;
  if (v.result === 'recorded') {
    const value = int(v.value);
    const recordedAt = instant(v.recordedAt);
    const nextDue = nullable(v.nextDue, instant);
    return value === null || recordedAt === null || nextDue === undefined ? null : { result: 'recorded', serviceName, value, recordedAt, nextDue };
  }
  if (v.result === 'outOfRange') {
    const value = int(v.value);
    const low = int(v.low);
    const high = int(v.high);
    return value === null || low === null || high === null ? null : { result: 'outOfRange', serviceName, value, low, high };
  }
  if (v.result === 'sendNumber') {
    if (v.reason === undefined) return { result: 'sendNumber', serviceName };
    const reason = str(v.reason, 32);
    return reason === null ? null : { result: 'sendNumber', serviceName, reason };
  }
  if (v.result === 'confirmLimit') return { result: 'confirmLimit', serviceName };
  return null;
}

export function parseBatch(body: unknown): { results: { serviceId: string; result: string; at?: string; reason?: string }[] } | null {
  const list = obj(body)?.results;
  if (!Array.isArray(list)) return null;
  const results: { serviceId: string; result: string; at?: string; reason?: string }[] = [];
  for (const entry of list) {
    const item = obj(entry);
    const serviceId = typeof item?.serviceId === 'string' && SERVICE_ID.test(item.serviceId) ? item.serviceId : null;
    const result = item?.result;
    if (serviceId === null || (result !== 'recorded' && result !== 'sendNumber' && result !== 'confirmLimit' && result !== 'outOfRange')) return null;
    const out: { serviceId: string; result: string; at?: string; reason?: string } = { serviceId, result };
    if (item?.at !== undefined) {
      const at = instant(item.at);
      if (at === null) return null;
      out.at = at;
    }
    if (item?.reason !== undefined) {
      const reason = str(item.reason, 32);
      if (reason === null) return null;
      out.reason = reason;
    }
    results.push(out);
  }
  return { results };
}

export function parseCover(body: unknown): { coveredUntil: string; services: number } | null {
  const v = obj(body);
  const coveredUntil = instant(v?.coveredUntil);
  const services = int(v?.services, 0, 1000);
  return coveredUntil === null || services === null ? null : { coveredUntil, services };
}

export function parseChannel(body: unknown): { channel: ChannelWord } | null {
  const channel = channelWord(obj(body)?.channel);
  return channel === null ? null : { channel };
}

export function parseAccepted(body: unknown): { accepted: boolean } | null {
  const accepted = obj(body)?.accepted;
  return typeof accepted === 'boolean' ? { accepted } : null;
}

export function parseResponded(body: unknown): { status: 'confirmed' | 'declined'; confirmedAt?: string } | null {
  const v = obj(body);
  if (v === null || (v.status !== 'confirmed' && v.status !== 'declined')) return null;
  if (v.confirmedAt === undefined) return { status: v.status };
  const confirmedAt = instant(v.confirmedAt);
  return confirmedAt === null ? null : { status: v.status, confirmedAt };
}

export function parseQueued(body: unknown): { queued: true } | null {
  return obj(body)?.queued === true ? { queued: true } : null;
}

export function parseSaved(body: unknown): { saved: true } | null {
  return obj(body)?.saved === true ? { saved: true } : null;
}

/** A text code's answer: `verified: true` is the only thing that means yes. */
export function isVerified(body: unknown): boolean {
  return obj(body)?.verified === true;
}

export const BASE64URL_KEY = /^[A-Za-z0-9_-]{1,256}$/;
export function parsePushKey(body: unknown): { publicKey: string } | null {
  const key = obj(body)?.publicKey;
  return typeof key === 'string' && BASE64URL_KEY.test(key) ? { publicKey: key } : null;
}

export function parseInvitationAnswer(body: unknown): { state: 'valid'; service: string; role: string; maskedPhone: string; expiresAt: string } | null {
  const v = obj(body);
  if (v === null || v.state !== 'valid') return null;
  const service = str(v.service);
  const role = str(v.role, 40);
  const maskedPhone = str(v.maskedPhone, 32);
  const expiresAt = instant(v.expiresAt);
  return service === null || role === null || maskedPhone === null || expiresAt === null ? null : { state: 'valid', service, role, maskedPhone, expiresAt };
}

/** The fields of a push subscription the back end takes, from a browser's `toJSON()`; null when it is not one. */
export function pickSubscription(value: unknown): { endpoint: string; keys: { p256dh: string; auth: string }; expirationTime?: number | null } | null {
  const v = obj(value);
  const endpoint = str(v?.endpoint, 2048);
  const keys = obj(v?.keys);
  const p256dh = str(keys?.p256dh, 256);
  const auth = str(keys?.auth, 256);
  if (endpoint === null || p256dh === null || auth === null) return null;
  try {
    if (new URL(endpoint).protocol !== 'https:') return null;
  } catch {
    return null;
  }
  const out: { endpoint: string; keys: { p256dh: string; auth: string }; expirationTime?: number | null } = { endpoint, keys: { p256dh, auth } };
  if (typeof v?.expirationTime === 'number' || v?.expirationTime === null) out.expirationTime = v.expirationTime as number | null;
  return out;
}
