// @vitest-environment node
import { afterEach, describe, expect, it, vi } from 'vitest';

const headerStore = vi.hoisted(() => ({ current: null as Headers | null }));
vi.mock('next/headers', () => ({
  headers: async () => {
    if (headerStore.current === null) throw new Error('outside a request');
    return headerStore.current;
  },
}));

import { ambientVisitorAddress, visitorAddress, visitorSource } from './visitorAddress';

const h = (init: Record<string, string>) => new Headers(init);

afterEach(() => {
  headerStore.current = null;
  vi.unstubAllEnvs();
});

describe('visitorAddress, x-forwarded-for (the default)', () => {
  it('is the right-most entry, the one the ingress added', () => {
    expect(visitorAddress(h({ 'x-forwarded-for': '203.0.113.9' }))).toBe('203.0.113.9');
    expect(visitorAddress(h({ 'x-forwarded-for': '198.51.100.1, 203.0.113.9' }))).toBe('203.0.113.9');
  });

  it('ignores a spoofed left-most entry', () => {
    expect(visitorAddress(h({ 'x-forwarded-for': '10.9.9.9, 192.0.2.77, 203.0.113.9' }))).toBe('203.0.113.9');
  });

  it('does not fall back to an earlier entry when the right-most is not an address', () => {
    expect(visitorAddress(h({ 'x-forwarded-for': '203.0.113.9, not-an-ip' }))).toBeNull();
    expect(visitorAddress(h({ 'x-forwarded-for': '203.0.113.9,' }))).toBeNull();
    expect(visitorAddress(h({ 'x-forwarded-for': '203.0.113.9, 1.2.3.4, 5.6.7.8' }))).toBe('5.6.7.8');
    expect(visitorAddress(h({ 'x-forwarded-for': '999.1.1.1' }))).toBeNull();
    expect(visitorAddress(h({ 'x-forwarded-for': '203.0.113.9 evil' }))).toBeNull();
  });

  it('takes ipv6, and drops a port or brackets', () => {
    expect(visitorAddress(h({ 'x-forwarded-for': '2001:db8::1' }))).toBe('2001:db8::1');
    expect(visitorAddress(h({ 'x-forwarded-for': '[2001:db8::1]:443' }))).toBe('2001:db8::1');
    expect(visitorAddress(h({ 'x-forwarded-for': '203.0.113.9:5555' }))).toBe('203.0.113.9');
  });

  it('is null with no header, an empty one, and ignores cf-connecting-ip', () => {
    expect(visitorAddress(h({}))).toBeNull();
    expect(visitorAddress(h({ 'x-forwarded-for': '' }))).toBeNull();
    expect(visitorAddress(h({ 'cf-connecting-ip': '203.0.113.9' }))).toBeNull();
  });
});

describe('visitorAddress, cf-connecting-ip (only when configured)', () => {
  it('uses that header and ignores x-forwarded-for', () => {
    const headers = h({ 'cf-connecting-ip': '203.0.113.9', 'x-forwarded-for': '198.51.100.1' });
    expect(visitorAddress(headers, 'cf-connecting-ip')).toBe('203.0.113.9');
  });

  it('is null for a list or a non-address', () => {
    expect(visitorAddress(h({ 'cf-connecting-ip': '1.2.3.4, 5.6.7.8' }), 'cf-connecting-ip')).toBeNull();
    expect(visitorAddress(h({ 'cf-connecting-ip': 'x' }), 'cf-connecting-ip')).toBeNull();
    expect(visitorAddress(h({ 'x-forwarded-for': '1.2.3.4' }), 'cf-connecting-ip')).toBeNull();
  });
});

describe('visitorSource', () => {
  it('defaults to x-forwarded-for and accepts only the two names', () => {
    expect(visitorSource(undefined)).toBe('x-forwarded-for');
    expect(visitorSource('')).toBe('x-forwarded-for');
    expect(visitorSource('anything')).toBe('x-forwarded-for');
    expect(visitorSource('cf-connecting-ip')).toBe('cf-connecting-ip');
    expect(visitorSource(' CF-Connecting-IP ')).toBe('cf-connecting-ip');
  });
});

describe('ambientVisitorAddress', () => {
  it('reads the request in progress, with the configured source', async () => {
    headerStore.current = h({ 'x-forwarded-for': '1.1.1.1, 203.0.113.9', 'cf-connecting-ip': '198.51.100.4' });
    expect(await ambientVisitorAddress()).toBe('203.0.113.9');
    vi.stubEnv('OVERWATCH_VISITOR_ADDRESS_SOURCE', 'cf-connecting-ip');
    expect(await ambientVisitorAddress()).toBe('198.51.100.4');
  });

  it('is undefined outside a request', async () => {
    expect(await ambientVisitorAddress()).toBeUndefined();
  });
});
