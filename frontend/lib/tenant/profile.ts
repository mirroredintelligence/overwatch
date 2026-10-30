import { headers } from 'next/headers';
import { normaliseHost } from '@/lib/auth/host';
import { callBackend } from '@/lib/fhir/hostCall';

// Server-only. The tenant's public profile (TEN-040 on the back end, TEN-049 here): its display name,
// the three words a page prints (system, referral system, coordination team) and its coordination
// phone. The tenant is the host (DEC-134 item 3), so the profile is read per host with the host as the
// Host header and no token; the back end answers as a path that is not there for a host nobody owns.
//
// It is cached in memory, per host and for a short time, so a page does not call the back end on every
// render, and a change a tenant makes shows within a minute. The key is the host and nothing else, a
// failure for one host is never answered with another host's profile, and the cache is bounded (hosts
// are chosen by whoever sends the request). It is not the Next.js data cache (the read is not a
// `fetch`, and a profile is never shared across hosts by a framework cache).
//
// Never an error for a page: a host nobody owns, a back end that is down, an answer that is not a
// profile and a missing configuration are all `null`, and every page then falls back to the product's
// own words and leaves out what only a tenant can say (H-T15: no invented words, no invented phone).

export type TenantWording = {
  readonly systemName: string;
  readonly referralSystemName: string;
  readonly coordinationTeamName: string;
};

export type TenantProfile = {
  readonly displayName: string;
  readonly timeZone: string;
  readonly locale: string;
  /** The tenant's three words, or null when it has no configuration in force. All three or none. */
  readonly wording: TenantWording | null;
  /** An organisational role number, or null. Never another contact. */
  readonly coordinationPhone: string | null;
  /**
   * Whether the tenant lets its staff share a session with support. Read from the profile when the
   * back end publishes it; off otherwise (fail closed). There is no environment variable for it.
   */
  readonly supportSharing: boolean;
};

export const PROFILE_TTL_MS = 60_000;
export const UNKNOWN_HOST_TTL_MS = 30_000;
export const UNAVAILABLE_TTL_MS = 5_000;
const MAX_ENTRIES = 200;
const PROFILE_PATH = '/public/tenant-profile';

const MAX_TEXT = 120;
const CONTROL = /[\u0000-\u001F\u007F]/;
const TIME_ZONE = /^[A-Za-z][A-Za-z0-9_+-]*(\/[A-Za-z0-9_+-]+)+$/;
const LOCALE = /^[a-z]{2,3}(-[A-Z]{2})?$/;
const PHONE = /^[0-9+()\s-]{3,20}$/;

function text(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  if (trimmed.length === 0 || trimmed.length > MAX_TEXT || CONTROL.test(trimmed)) return null;
  return trimmed;
}

function wordingOf(value: unknown): TenantWording | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null;
  const { systemName, referralSystemName, coordinationTeamName } = value as Record<string, unknown>;
  const system = text(systemName);
  const referral = text(referralSystemName);
  const team = text(coordinationTeamName);
  // All three or none: part of a set of words is never shown.
  if (system === null || referral === null || team === null) return null;
  return Object.freeze({ systemName: system, referralSystemName: referral, coordinationTeamName: team });
}

function phoneOf(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const phone = value.trim();
  if (!PHONE.test(phone) || (phone.match(/\d/g) ?? []).length < 3) return null;
  return phone;
}

/**
 * The profile from the back end's answer, or null when the answer is not a profile. Only the fields
 * this module knows are kept (an id, a status or an epoch in the answer is dropped). A wrong phone is
 * dropped, not shown; a wrong name, zone or locale refuses the whole profile.
 */
export function parseProfile(body: unknown): TenantProfile | null {
  if (typeof body !== 'object' || body === null || Array.isArray(body)) return null;
  const source = body as Record<string, unknown>;
  const displayName = text(source.displayName);
  const timeZone = typeof source.timeZone === 'string' && TIME_ZONE.test(source.timeZone) ? source.timeZone : null;
  const locale = typeof source.locale === 'string' && LOCALE.test(source.locale) ? source.locale : null;
  if (displayName === null || timeZone === null || locale === null) return null;
  return Object.freeze({
    displayName,
    timeZone,
    locale,
    wording: wordingOf(source.wording),
    coordinationPhone: phoneOf(source.coordinationPhone),
    supportSharing: source.supportSharing === true,
  });
}

type Entry = { profile: TenantProfile | null; expiresAt: number };
const cache = new Map<string, Entry>();
const inFlight = new Map<string, Promise<Entry>>();

/** For tests: forget everything read so far. */
export function resetProfileCache(): void {
  cache.clear();
  inFlight.clear();
}

async function fetchEntry(host: string, now: number): Promise<Entry> {
  try {
    const reply = await callBackend({ method: 'GET', path: PROFILE_PATH, host });
    if (reply.status === 200) {
      const profile = parseProfile(reply.body);
      return { profile, expiresAt: now + (profile === null ? UNAVAILABLE_TTL_MS : PROFILE_TTL_MS) };
    }
    return { profile: null, expiresAt: now + (reply.status === 404 ? UNKNOWN_HOST_TTL_MS : UNAVAILABLE_TTL_MS) };
  } catch {
    // An unreachable back end and a missing configuration are the same to a page. Nothing of the
    // error (a URL, a host) is kept.
    return { profile: null, expiresAt: now + UNAVAILABLE_TTL_MS };
  }
}

function remember(host: string, entry: Entry): void {
  cache.delete(host);
  cache.set(host, entry);
  while (cache.size > MAX_ENTRIES) {
    const oldest = cache.keys().next().value;
    if (oldest === undefined) break;
    cache.delete(oldest);
  }
}

/** The profile of the tenant that owns `host`, or null. `now` is for tests. */
export async function readTenantProfile(host: string | null, now: Date = new Date()): Promise<TenantProfile | null> {
  const key = host === null ? null : normaliseHost(host);
  if (key === null) return null;
  const at = now.getTime();

  const cached = cache.get(key);
  if (cached !== undefined && at < cached.expiresAt) return cached.profile;

  let pending = inFlight.get(key);
  if (pending === undefined) {
    pending = fetchEntry(key, at).then((entry) => {
      remember(key, entry);
      return entry;
    });
    inFlight.set(key, pending);
    void pending.finally(() => inFlight.delete(key));
  }
  return (await pending).profile;
}

/** The profile of the host the current request was addressed to. For Server Components. */
export async function currentProfile(): Promise<TenantProfile | null> {
  return readTenantProfile((await headers()).get('host'));
}
