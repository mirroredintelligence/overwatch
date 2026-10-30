import { describe, expect, it, beforeEach, vi } from 'vitest';
import { cookieWrites, cookiesMock, lastWrite, requestWithCookies, resetCookieWrites } from '@/test/cookies';
import { CSRF_COOKIE, checkCsrf, csrfTokenFor } from '@/lib/auth/csrf';
import { SESSION_COOKIE } from '@/lib/auth/session';
import { sessionFor } from '@/test/requests';
import { TENANTS } from '@/test/tenants';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { checkLinkCsrf, issueLinkCsrf, LINK_CSRF_COOKIE, linkCsrfPath } from './csrf';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

const TOKEN = 'RecordedLinkTokenAbcdef';
const VALUE = 'a'.repeat(64);
const URL_ = `https://tenant-a.example.test/api/bff/links/${TOKEN}`;

beforeEach(() => {
  resetCookieWrites();
  cookiesMock.mockClear();
});

describe('linkCsrfPath', () => {
  it('scopes the cookie to this link’s own BFF path, so two links in one browser do not collide', () => {
    expect(linkCsrfPath(TOKEN)).toBe(`/api/bff/links/${TOKEN}`);
  });
});

describe('issueLinkCsrf', () => {
  it('sets a cookie that script cannot read, sent only on strict same-site requests to this link', async () => {
    await issueLinkCsrf(TOKEN, VALUE);
    const write = lastWrite(LINK_CSRF_COOKIE);
    expect(write?.value).toBe(VALUE);
    expect(write?.options).toMatchObject({ httpOnly: true, sameSite: 'strict', path: `/api/bff/links/${TOKEN}` });
    expect(write?.options.maxAge).toBeGreaterThan(0);
    expect(cookieWrites).toHaveLength(1);
  });
});

describe('checkLinkCsrf', () => {
  it('is true only when the header equals the cookie for this link', () => {
    const request = requestWithCookies(URL_, { [LINK_CSRF_COOKIE]: VALUE }, {
      method: 'POST',
      headers: { 'X-CSRF-Token': VALUE },
    });
    expect(checkLinkCsrf(request, TOKEN)).toBe(true);
  });

  it('is false with no header, no cookie, or a header that is not the cookie', () => {
    const cookieOnly = requestWithCookies(URL_, { [LINK_CSRF_COOKIE]: VALUE }, { method: 'POST' });
    const headerOnly = requestWithCookies(URL_, {}, { method: 'POST', headers: { 'X-CSRF-Token': VALUE } });
    const wrong = requestWithCookies(URL_, { [LINK_CSRF_COOKIE]: VALUE }, {
      method: 'POST',
      headers: { 'X-CSRF-Token': 'b'.repeat(64) },
    });
    expect(checkLinkCsrf(cookieOnly, TOKEN)).toBe(false);
    expect(checkLinkCsrf(headerOnly, TOKEN)).toBe(false);
    expect(checkLinkCsrf(wrong, TOKEN)).toBe(false);
  });

  it('is false for an empty value, so a blank header cannot match a blank cookie', () => {
    const request = requestWithCookies(URL_, { [LINK_CSRF_COOKIE]: '' }, { method: 'POST', headers: { 'X-CSRF-Token': '' } });
    expect(checkLinkCsrf(request, TOKEN)).toBe(false);
  });
});


// Opening a link in a browser that holds a staff session must change nothing of the staff session
// (TEN-046, audit D 3.1): the link has its own cookie, name and path, and its own check.
describe('the link CSRF is separate from the staff CSRF (TEN-046)', () => {
  const STAFF = sessionFor(TENANTS.A, 'advisor', { sub: 'stf-person-1' });

  it('has its own cookie name, not the staff one', () => {
    expect(LINK_CSRF_COOKIE).not.toBe(CSRF_COOKIE);
    expect(LINK_CSRF_COOKIE).toBe('diucs_link_csrf');
  });

  it('writes the link cookie and no other cookie when a link is opened, so the staff token is never rotated', async () => {
    seedStaff();
    await issueLinkCsrf(TOKEN, VALUE);
    expect(cookieWrites.map((w) => w.name)).toEqual([LINK_CSRF_COOKIE]);
    expect(cookieWrites.some((w) => w.name === CSRF_COOKIE || w.name === SESSION_COOKIE)).toBe(false);
  });

  it('is limited to the path of its own link, so no staff route and no other link receives it', async () => {
    await issueLinkCsrf(TOKEN, VALUE);
    const path = String(lastWrite(LINK_CSRF_COOKIE)?.options.path);
    expect(path).toBe(`/api/bff/links/${TOKEN}`);
    expect(`/api/bff/session`.startsWith(path)).toBe(false);
    expect(`/api/bff/links/OtherLinkTokenAbcdefg`.startsWith(path)).toBe(false);
  });

  it('does not accept the staff pair for a link', () => {
    const staff = csrfTokenFor(STAFF, 'N'.repeat(43));
    const request = requestWithCookies(URL_, { [CSRF_COOKIE]: staff }, { method: 'POST', headers: { 'X-CSRF-Token': staff } });
    expect(checkLinkCsrf(request, TOKEN)).toBe(false);
  });

  it('does not accept the link pair for a staff request', () => {
    const request = requestWithCookies(URL_, { [LINK_CSRF_COOKIE]: VALUE }, { method: 'POST', headers: { 'X-CSRF-Token': VALUE } });
    expect(checkCsrf(request, STAFF)).toBe(false);
  });

  it('does not accept one link’s pair on another link’s path', () => {
    const request = requestWithCookies(`https://tenant-a.example.test/api/bff/links/OtherLinkTokenAbcdefg`, { [LINK_CSRF_COOKIE]: VALUE }, {
      method: 'POST',
      headers: { 'X-CSRF-Token': VALUE },
    });
    expect(checkLinkCsrf(request, TOKEN)).toBe(false);
  });

  function seedStaff() {
    vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  }
});
