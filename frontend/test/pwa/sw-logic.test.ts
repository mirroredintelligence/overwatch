// @vitest-environment node
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import vm from 'node:vm';
import { describe, expect, it } from 'vitest';

// The service worker's logic lives in public/sw-logic.js, a classic script, so the worker
// file that ships is the file under test. It is loaded here in an empty sandbox.
const SOURCE = readFileSync(join(process.cwd(), 'public', 'sw-logic.js'), 'utf8');

type Logic = {
  handlePush: (data: unknown) => { title: string; body: string; data: { url: string } };
  pickClientOrOpen: (
    clientUrls: string[],
    url: string,
    origin: string,
  ) => { kind: 'focus'; index: number } | { kind: 'open'; url: string };
  isCacheable: (request: string | { url: string; method?: string }) => boolean;
};

function load(): Logic {
  const scope: { DiucsSw?: Logic } = {};
  vm.createContext({ self: scope });
  vm.runInContext(SOURCE, vm.createContext({ self: scope }));
  if (!scope.DiucsSw) throw new Error('sw-logic.js does not expose DiucsSw');
  return scope.DiucsSw;
}

const sw = load();

describe('handlePush', () => {
  it('keeps only title, body and url, and drops every other field of the payload', () => {
    const shown = sw.handlePush({
      title: 'UCR West: confirm or update',
      body: 'We have 3 referrals recorded. Reply by 10:30.',
      url: '/app/respond/s1',
      postcode: 'DT4 8XX',
    });
    expect(shown).toEqual({
      title: 'UCR West: confirm or update',
      body: 'We have 3 referrals recorded. Reply by 10:30.',
      data: { url: '/app/respond/s1' },
    });
    expect(JSON.stringify(shown)).not.toContain('DT4');
  });

  it('sends an off-origin or protocol-relative url to /app', () => {
    expect(sw.handlePush({ title: 't', body: 'b', url: 'https://evil.example/x' }).data.url).toBe('/app');
    expect(sw.handlePush({ title: 't', body: 'b', url: '//evil.example/x' }).data.url).toBe('/app');
    expect(sw.handlePush({ title: 't', body: 'b' }).data.url).toBe('/app');
  });
});

describe('pickClientOrOpen', () => {
  const origin = 'https://app.test';

  it('focuses an open client whose URL starts with the origin', () => {
    expect(sw.pickClientOrOpen(['https://other.test/x', 'https://app.test/app'], '/app/respond/s1', origin)).toEqual({
      kind: 'focus',
      index: 1,
    });
  });

  it('opens the url when no client is open', () => {
    expect(sw.pickClientOrOpen([], '/app/respond/s1', origin)).toEqual({ kind: 'open', url: '/app/respond/s1' });
  });

  it('opens /app for an off-origin url, even with no client open', () => {
    expect(sw.pickClientOrOpen([], 'https://evil.example/', origin)).toEqual({ kind: 'open', url: '/app' });
  });
});

describe('isCacheable', () => {
  it('caches the offline page and the static build assets', () => {
    expect(sw.isCacheable('/offline')).toBe(true);
    expect(sw.isCacheable('/_next/static/chunks/main.js')).toBe(true);
  });

  it('never caches the BFF, the app or a link page', () => {
    expect(sw.isCacheable('/api/bff/board')).toBe(false);
    expect(sw.isCacheable('/app')).toBe(false);
    expect(sw.isCacheable('/l/abc')).toBe(false);
    expect(sw.isCacheable({ url: '/api/bff/reporter/services', method: 'GET' })).toBe(false);
  });
});
