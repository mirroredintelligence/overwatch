import { describe, expect, it, beforeEach, vi } from 'vitest';
import { cookieWrites, cookiesMock, lastWrite, requestWithCookies, resetCookieWrites } from '@/test/cookies';
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
