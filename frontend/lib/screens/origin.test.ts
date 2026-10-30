// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { isSameOriginRequest } from './origin';

// A request that starts a pairing or makes a session with no session of its own cannot use the
// double-submit token, so it must come from this site's own pages: a browser says so with
// `Sec-Fetch-Site` and `Origin`, and a page of another site cannot forge either.

function post(headers: Record<string, string>, url = 'https://tenant-a.example.test/api/bff/screens/pairing') {
  return new Request(url, { method: 'POST', headers });
}

describe('isSameOriginRequest', () => {
  it('accepts a request the browser marks same-origin', () => {
    expect(isSameOriginRequest(post({ 'Sec-Fetch-Site': 'same-origin' }))).toBe(true);
  });

  it('accepts an Origin that is the host the request came to', () => {
    expect(isSameOriginRequest(post({ Origin: 'https://tenant-a.example.test', Host: 'tenant-a.example.test' }))).toBe(true);
  });

  it('accepts a request that says neither, since only a browser can be tricked into a cross-site request and every browser says one of them', () => {
    expect(isSameOriginRequest(post({}))).toBe(true);
  });

  it.each(['cross-site', 'same-site', 'none', ''])('refuses Sec-Fetch-Site %j', (value) => {
    expect(isSameOriginRequest(post({ 'Sec-Fetch-Site': value }))).toBe(false);
  });

  it.each([
    'https://evil.example',
    'null',
    'https://tenant-b.example.test',
    'https://tenant-a.example.test.evil.example',
    'not an origin',
    'https://tenant-a.example.test:8443',
  ])('refuses the Origin %j', (origin) => {
    expect(isSameOriginRequest(post({ Origin: origin, Host: 'tenant-a.example.test' }))).toBe(false);
  });

  it('refuses when the two disagree, in either direction', () => {
    expect(isSameOriginRequest(post({ 'Sec-Fetch-Site': 'same-origin', Origin: 'https://evil.example', Host: 'tenant-a.example.test' }))).toBe(false);
    expect(isSameOriginRequest(post({ 'Sec-Fetch-Site': 'cross-site', Origin: 'https://tenant-a.example.test', Host: 'tenant-a.example.test' }))).toBe(false);
  });
});
