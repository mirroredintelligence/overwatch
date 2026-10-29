import { describe, expect, it } from 'vitest';
import { beginInteraction, newTraceparent, TRACEPARENT_PATTERN, withTraceparent } from './trace';

describe('newTraceparent', () => {
  it('is a W3C traceparent: version 00, a 32-hex trace id, a 16-hex parent id and the sampled flag', () => {
    expect(newTraceparent()).toMatch(/^00-[0-9a-f]{32}-[0-9a-f]{16}-01$/);
    expect(newTraceparent()).toMatch(TRACEPARENT_PATTERN);
  });

  it('gives a different parent id each time', () => {
    expect(newTraceparent()).not.toBe(newTraceparent());
  });
});

describe('withTraceparent', () => {
  it('adds a traceparent header to a request that has none', () => {
    const init = withTraceparent({ method: 'GET', cache: 'no-store' });

    expect(new Headers(init.headers).get('traceparent')).toMatch(TRACEPARENT_PATTERN);
    expect(init.method).toBe('GET');
    expect(init.cache).toBe('no-store');
  });

  it('keeps the headers the request already has', () => {
    const init = withTraceparent({
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': 'token-value' },
    });
    const headers = new Headers(init.headers);

    expect(headers.get('content-type')).toBe('application/json');
    expect(headers.get('x-csrf-token')).toBe('token-value');
    expect(headers.get('traceparent')).toMatch(TRACEPARENT_PATTERN);
  });

  it('keeps a traceparent the caller already set', () => {
    const own = `00-${'a'.repeat(32)}-${'b'.repeat(16)}-01`;

    const init = withTraceparent({ headers: { traceparent: own } });

    expect(new Headers(init.headers).get('traceparent')).toBe(own);
  });

  it('shares the trace id within one interaction, and gives each request its own parent id', () => {
    const trace = beginInteraction();

    const first = new Headers(withTraceparent({}).headers).get('traceparent') ?? '';
    const second = new Headers(withTraceparent({}).headers).get('traceparent') ?? '';

    expect(first.split('-')[1]).toBe(trace);
    expect(second.split('-')[1]).toBe(trace);
    expect(first).not.toBe(second);
  });

  it('does not change the init it is given', () => {
    const init: RequestInit = { method: 'GET' };

    withTraceparent(init);

    expect(init).toEqual({ method: 'GET' });
  });
});
