import { describe, expect, it } from 'vitest';
import { fakeBackendToken } from '@/test/backendToken';
import { readIssuedToken } from './tokenClaims';

const NOW = new Date('2026-10-30T09:00:00.000Z');
const nowSeconds = Math.floor(NOW.getTime() / 1000);

function token(claims: Record<string, unknown>) {
  const part = (value: unknown) => Buffer.from(JSON.stringify(value)).toString('base64url');
  return `${part({ alg: 'HS256', typ: 'JWT' })}.${part(claims)}.sig`;
}
const base = { sub: 'stf-1', role: 'advisor', services: [], tenant: 'trust-a', epoch: 1, aud: 'diucs-api', exp: nowSeconds + 3600 };

describe('readIssuedToken', () => {
  it('reads the claims the back end put in the token it issued', () => {
    const claims = readIssuedToken(fakeBackendToken({ tenant: 'trust-b', role: 'lead', sub: 'stf-9', exp: nowSeconds + 60 }, NOW), NOW);
    expect(claims).toEqual({ sub: 'stf-9', role: 'lead', services: [], tenant: 'trust-b', exp: nowSeconds + 60, device: undefined });
  });

  it('keeps the device and the services when the token has them', () => {
    const claims = readIssuedToken(token({ ...base, services: ['svc-1'], device: 'dev-1' }), NOW);
    expect(claims).toMatchObject({ services: ['svc-1'], device: 'dev-1' });
  });

  it('takes an absent services claim as none', () => {
    const { services: _services, ...rest } = base;
    void _services;
    expect(readIssuedToken(token(rest), NOW)?.services).toEqual([]);
  });

  it.each([
    ['no tenant', { tenant: undefined }],
    ['an empty tenant', { tenant: '' }],
    ['a network id as the tenant', { tenant: 'net-capacity' }],
    ['a tenant that is not text', { tenant: 7 }],
    ['a tenant that is a list', { tenant: ['trust-a'] }],
    ['an upper-case tenant id', { tenant: 'Trust-A' }],
    ['no audience', { aud: undefined }],
    ['the operator audience', { aud: 'diucs-ops' }],
    ['an audience list', { aud: ['diucs-api'] }],
    ['no subject', { sub: undefined }],
    ['an empty subject', { sub: '' }],
    ['a subject that is too long', { sub: 'x'.repeat(200) }],
    ['no role', { role: undefined }],
    ['a role that is not text', { role: 4 }],
    ['services that are not a list', { services: 'svc-1' }],
    ['services that are not text', { services: [1] }],
    ['no expiry', { exp: undefined }],
    ['an expiry that is not a number', { exp: '9999999999' }],
    ['an expiry that has passed', { exp: nowSeconds - 1 }],
    ['an expiry at this instant', { exp: nowSeconds }],
    ['an expiry that is not a whole number', { exp: nowSeconds + 10.5 }],
    ['a device that is not text', { device: 3 }],
  ])('refuses a token with %s', (_name, change) => {
    expect(readIssuedToken(token({ ...base, ...change }), NOW)).toBeNull();
  });

  it.each([
    '',
    'not-a-token',
    'a.b',
    'a.b.c.d',
    '..',
    `${Buffer.from('{}').toString('base64url')}.${Buffer.from('[]').toString('base64url')}.s`,
    `${Buffer.from('{}').toString('base64url')}.${Buffer.from('"text"').toString('base64url')}.s`,
    `${Buffer.from('{}').toString('base64url')}.${Buffer.from('not json').toString('base64url')}.s`,
    `${Buffer.from('{}').toString('base64url')}.!!!!.s`,
  ])('refuses %j, which is not a token', (value) => {
    expect(readIssuedToken(value, NOW)).toBeNull();
  });

  it('refuses a token longer than the back end would issue', () => {
    expect(readIssuedToken(token({ ...base, pad: 'x'.repeat(9000) }), NOW)).toBeNull();
  });

  it('refuses what is not text', () => {
    for (const value of [null, undefined, 7, {}]) {
      expect(readIssuedToken(value as unknown as string, NOW)).toBeNull();
    }
  });
});
