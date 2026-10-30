// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BACKEND_ROOT } from '@/test/fixtures/links';
import { PROFILE_URL, resetProfileRequests, seenProfileRequests } from '@/test/msw/handlers/profile';
import { server } from '@/test/msw/server';
import { TENANTS } from '@/test/tenants';
import { parseProfile, PROFILE_TTL_MS, readTenantProfile, resetProfileCache, UNAVAILABLE_TTL_MS, UNKNOWN_HOST_TTL_MS } from './profile';

// The tenant's public profile: its name, its words and its coordination phone (TEN-040 on the back
// end, TEN-049 here). It is read on the server, per host, with a short in-memory cache that is keyed by
// the host and nothing else, so one tenant's profile is never shown for another host. The profile
// carries no token, no tenant id and nothing personal.

const A = TENANTS.A;
const B = TENANTS.B;
const C = TENANTS.C;

beforeEach(() => {
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND_ROOT}/fhir`);
  resetProfileCache();
  resetProfileRequests();
});
afterEach(() => vi.unstubAllEnvs());

const GOOD = {
  displayName: 'Sample Area A',
  timeZone: 'Europe/London',
  locale: 'en-GB',
  wording: { systemName: 'Capacity A', referralSystemName: 'Referral system A', coordinationTeamName: 'Access team A' },
  coordinationPhone: '01632 960001',
};

describe('parseProfile', () => {
  it('reads the profile the back end answers', () => {
    expect(parseProfile(GOOD)).toEqual({ ...GOOD, supportSharing: false });
  });

  it('reads a profile with no wording and no phone (a tenant with no configuration in force)', () => {
    expect(parseProfile({ ...GOOD, wording: null, coordinationPhone: null })).toEqual({
      ...GOOD,
      wording: null,
      coordinationPhone: null,
      supportSharing: false,
    });
  });

  it('reads the support-sharing flag only when it is the boolean true; absent or anything else is off', () => {
    expect(parseProfile({ ...GOOD, supportSharing: true })?.supportSharing).toBe(true);
    for (const value of [undefined, false, 'true', 1, null, {}]) {
      expect(parseProfile({ ...GOOD, supportSharing: value })?.supportSharing).toBe(false);
    }
  });

  it('is frozen, so a component that changes it cannot change what another request sees', () => {
    const profile = parseProfile(GOOD);
    expect(Object.isFrozen(profile)).toBe(true);
    expect(Object.isFrozen(profile?.wording)).toBe(true);
    expect(() => {
      (profile as { displayName: string }).displayName = 'Other';
    }).toThrow();
  });

  it('keeps only the fields it knows: an id, a status or anything else the answer carries is dropped', () => {
    const profile = parseProfile({ ...GOOD, id: 'trust-b', tenantId: 'trust-b', epoch: 4, legalName: 'Sample Legal Name', status: 'active' });
    expect(Object.keys(profile ?? {}).sort()).toEqual(['coordinationPhone', 'displayName', 'locale', 'supportSharing', 'timeZone', 'wording']);
    expect(JSON.stringify(profile)).not.toMatch(/trust-b|Legal|epoch/);
  });

  it.each([
    ['no display name', { displayName: undefined }],
    ['an empty display name', { displayName: '' }],
    ['a blank display name', { displayName: '   ' }],
    ['a display name that is not text', { displayName: 7 }],
    ['a display name that is too long', { displayName: 'x'.repeat(121) }],
    ['a display name with a control character', { displayName: 'Sample\u0000Area' }],
    ['a display name with a newline', { displayName: 'Sample\nArea' }],
    ['a time zone that is not a zone', { timeZone: 'sometime' }],
    ['no time zone', { timeZone: undefined }],
    ['a locale that is not a locale', { locale: 'English (UK)' }],
    ['no locale', { locale: undefined }],
  ])('refuses a profile with %s', (_name, change) => {
    expect(parseProfile({ ...GOOD, ...change })).toBeNull();
  });

  it.each([
    ['wording that is a text', { wording: 'words' }],
    ['wording that is a list', { wording: [] }],
    ['a missing word', { wording: { systemName: 'Capacity A', referralSystemName: 'Referral system A' } }],
    ['a word that is not text', { wording: { ...GOOD.wording, systemName: 5 } }],
    ['an empty word', { wording: { ...GOOD.wording, referralSystemName: '' } }],
    ['a word that is too long', { wording: { ...GOOD.wording, coordinationTeamName: 'x'.repeat(121) } }],
    ['a word with a control character', { wording: { ...GOOD.wording, systemName: 'Cap\u0007acity' } }],
  ])('drops the wording, never part of it, for %s', (_name, change) => {
    expect(parseProfile({ ...GOOD, ...change })?.wording).toBeNull();
  });

  it.each(['0800 NOT A PHONE', '<script>', '1', '01632 960001 ext 5', 'x'.repeat(40), 7, ''])(
    'drops a phone of %j rather than show a wrong number',
    (phone) => {
      const profile = parseProfile({ ...GOOD, coordinationPhone: phone });
      expect(profile).not.toBeNull();
      expect(profile?.coordinationPhone).toBeNull();
    },
  );

  it.each(['01632 960001', '+44 1632 960001', '(01632) 960001', '0800 960 0001', '111'])('keeps the phone %s', (phone) => {
    expect(parseProfile({ ...GOOD, coordinationPhone: phone })?.coordinationPhone).toBe(phone);
  });

  it('refuses what is not an object', () => {
    for (const value of [null, undefined, 'x', 7, [], [GOOD]]) expect(parseProfile(value)).toBeNull();
  });

  it('keeps the words as text and does not interpret them (markup is shown, never run)', () => {
    expect(parseProfile({ ...GOOD, displayName: '<b>Sample</b> Area' })?.displayName).toBe('<b>Sample</b> Area');
  });
});

describe('readTenantProfile: what is sent', () => {
  it('asks the back end for the profile of the host, with the host as the Host header, and nothing else that names a tenant', async () => {
    await readTenantProfile(A.host);
    expect(seenProfileRequests).toHaveLength(1);
    expect(seenProfileRequests[0]?.host).toBe(A.host);
    expect(seenProfileRequests[0]?.headerNames.filter((n) => /authorization|tenant|scope|network|cookie/.test(n))).toEqual([]);
  });

  it('does not ask for a host that is not a host name', async () => {
    for (const host of [null, '', 'a.test/evil', 'user@a.test', 'a b']) {
      expect(await readTenantProfile(host)).toBeNull();
    }
    expect(seenProfileRequests).toHaveLength(0);
  });
});

describe('readTenantProfile: what comes back', () => {
  it('is the profile of the host, and a different profile for another host', async () => {
    expect((await readTenantProfile(A.host))?.displayName).toBe('Sample Area A');
    expect((await readTenantProfile(B.host))?.displayName).toBe('Sample Area B');
  });

  it('is a profile with no wording for a tenant that has none', async () => {
    expect(await readTenantProfile(C.host)).toMatchObject({ displayName: 'Sample Area C', wording: null, coordinationPhone: null });
  });

  it('is null for a host no tenant owns', async () => {
    expect(await readTenantProfile('nobody.example.test')).toBeNull();
  });

  it.each([
    ['a 500', () => HttpResponse.json({}, { status: 500 })],
    ['a 429', () => HttpResponse.json({}, { status: 429 })],
    ['a 403', () => HttpResponse.json({}, { status: 403 })],
    ['a body that is not JSON', () => new HttpResponse('<html>', { status: 200 })],
    ['a body that is not a profile', () => HttpResponse.json({ hello: 'world' })],
    ['a connection that fails', () => HttpResponse.error()],
  ])('is null, never an error, for %s', async (_name, answer) => {
    server.use(http.get(PROFILE_URL, answer));
    expect(await readTenantProfile(A.host)).toBeNull();
  });

  it('is null, never an error, when the back end address is not configured', async () => {
    vi.stubEnv('DIUCS_FHIR_BASE_URL', '');
    expect(await readTenantProfile(A.host)).toBeNull();
  });
});

describe('readTenantProfile: the cache', () => {
  it('asks the back end once for a host within the time to live', async () => {
    const now = new Date('2026-10-30T10:00:00Z');
    await readTenantProfile(A.host, now);
    await readTenantProfile(A.host, new Date(now.getTime() + PROFILE_TTL_MS - 1));
    expect(seenProfileRequests).toHaveLength(1);
  });

  it('asks again when the time to live has passed, and shows a change the tenant made', async () => {
    const now = new Date('2026-10-30T10:00:00Z');
    expect((await readTenantProfile(A.host, now))?.displayName).toBe('Sample Area A');
    server.use(http.get(PROFILE_URL, () => HttpResponse.json({ ...GOOD, displayName: 'Renamed Area A' })));
    expect((await readTenantProfile(A.host, new Date(now.getTime() + PROFILE_TTL_MS)))?.displayName).toBe('Renamed Area A');
    expect(seenProfileRequests.length).toBeGreaterThanOrEqual(1);
  });

  it('keeps the time to live short: one minute', () => {
    expect(PROFILE_TTL_MS).toBe(60_000);
  });

  it('keys the cache by host alone: a host never gets another host’s profile, even when its own read fails', async () => {
    const now = new Date('2026-10-30T10:00:00Z');
    expect((await readTenantProfile(A.host, now))?.displayName).toBe('Sample Area A');
    expect(await readTenantProfile('nobody.example.test', now)).toBeNull();
    server.use(http.get(PROFILE_URL, () => HttpResponse.json({}, { status: 503 })));
    expect(await readTenantProfile(B.host, now)).toBeNull();
  });

  it('treats a host without regard to case, and a port as another host', async () => {
    const now = new Date('2026-10-30T10:00:00Z');
    await readTenantProfile(A.host.toUpperCase(), now);
    await readTenantProfile(A.host, now);
    expect(seenProfileRequests).toHaveLength(1);
    await readTenantProfile(`${A.host}:3000`, now);
    expect(seenProfileRequests).toHaveLength(2);
  });

  it('remembers a host nobody owns for a short while, so a flood of unknown hosts is not a flood of calls', async () => {
    const now = new Date('2026-10-30T10:00:00Z');
    await readTenantProfile('nobody.example.test', now);
    await readTenantProfile('nobody.example.test', new Date(now.getTime() + UNKNOWN_HOST_TTL_MS - 1));
    expect(seenProfileRequests).toHaveLength(1);
    await readTenantProfile('nobody.example.test', new Date(now.getTime() + UNKNOWN_HOST_TTL_MS));
    expect(seenProfileRequests).toHaveLength(2);
  });

  it('remembers a failure only briefly, so a back end that comes back is used again', async () => {
    const now = new Date('2026-10-30T10:00:00Z');
    let calls = 0;
    server.use(http.get(PROFILE_URL, () => {
      calls += 1;
      return HttpResponse.json({}, { status: 503 });
    }));
    expect(await readTenantProfile(A.host, now)).toBeNull();
    expect(await readTenantProfile(A.host, new Date(now.getTime() + UNAVAILABLE_TTL_MS - 1))).toBeNull();
    expect(calls).toBe(1);
    server.resetHandlers();
    expect((await readTenantProfile(A.host, new Date(now.getTime() + UNAVAILABLE_TTL_MS)))?.displayName).toBe('Sample Area A');
    expect(UNAVAILABLE_TTL_MS).toBeLessThan(UNKNOWN_HOST_TTL_MS);
  });

  it('asks once for two reads of one host at the same moment', async () => {
    const [one, two] = await Promise.all([readTenantProfile(A.host), readTenantProfile(A.host)]);
    expect(one).toBe(two);
    expect(seenProfileRequests).toHaveLength(1);
  });

  it('holds a bounded number of hosts, so hosts chosen by a caller cannot grow it without end', async () => {
    const now = new Date('2026-10-30T10:00:00Z');
    for (let i = 0; i < 300; i += 1) await readTenantProfile(`unknown-${i}.example.test`, now);
    resetProfileRequests();
    await readTenantProfile('unknown-299.example.test', now);
    expect(seenProfileRequests).toHaveLength(0);
    await readTenantProfile('unknown-0.example.test', now);
    expect(seenProfileRequests).toHaveLength(1);
  });

  it('does not use the Next.js data cache: the call is not a fetch', async () => {
    const spy = vi.spyOn(globalThis, 'fetch');
    await readTenantProfile(A.host);
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });
});
