// @vitest-environment node
import { jwtVerify } from 'jose';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { BACKEND_JWT_SECRET, OID_ADVISOR, TENANT_A } from '@/test/oidc/constants';
import { backendTokenExpiresAt, mapRoles, mintBackendToken, safeNext } from './staff';

afterEach(() => vi.unstubAllEnvs());

describe('mapRoles', () => {
  it('maps one app role to its role', () => {
    expect(mapRoles(['DIUCS.Lead'])).toBe('lead');
    expect(mapRoles(['DIUCS.Advisor'])).toBe('advisor');
    expect(mapRoles(['DIUCS.Clinical'])).toBe('clinical');
    expect(mapRoles(['DIUCS.Owner'])).toBe('owner');
    expect(mapRoles(['DIUCS.Planning'])).toBe('exec');
  });

  it('returns null for roles it does not know', () => {
    expect(mapRoles(['Some.Other.Role'])).toBeNull();
    expect(mapRoles([])).toBeNull();
  });

  it('picks the highest of several, in the order lead, clinical, advisor, owner, exec, support', () => {
    expect(mapRoles(['DIUCS.Advisor', 'DIUCS.Lead'])).toBe('lead');
    expect(mapRoles(['DIUCS.Lead', 'DIUCS.Advisor'])).toBe('lead');
    expect(mapRoles(['DIUCS.Advisor', 'DIUCS.Clinical'])).toBe('clinical');
    expect(mapRoles(['DIUCS.Owner', 'DIUCS.Advisor'])).toBe('advisor');
    expect(mapRoles(['DIUCS.Planning', 'DIUCS.Owner'])).toBe('owner');
    expect(mapRoles(['DIUCS.Planning', 'DIUCS.Support'], { allowSupport: true })).toBe('exec');
  });

  it('ignores an unknown role beside a known one', () => {
    expect(mapRoles(['Other.Role', 'DIUCS.Advisor'])).toBe('advisor');
  });

  it('gives the support role only where the caller says support is allowed', () => {
    expect(mapRoles(['DIUCS.Support'])).toBeNull();
    expect(mapRoles(['DIUCS.Support'], { allowSupport: false })).toBeNull();
    expect(mapRoles(['DIUCS.Support'], { allowSupport: true })).toBe('support');
    expect(mapRoles(['DIUCS.Support', 'DIUCS.Lead'])).toBe('lead');
  });

  it.each([
    ['nothing', undefined],
    ['null', null],
    ['a string', 'DIUCS.Lead'],
    ['an object', { 0: 'DIUCS.Lead' }],
    ['a number', 7],
    ['a list of non-strings', [7, null, { a: 1 }]],
    ['another case', ['diucs.lead']],
    ['a padded name', [' DIUCS.Lead']],
    ['an object prototype key', ['__proto__', 'constructor', 'toString', 'hasOwnProperty']],
  ])('returns null for %s', (_name, claim) => {
    expect(mapRoles(claim)).toBeNull();
  });
});

describe('backendTokenExpiresAt', () => {
  it('is eight hours on', () => {
    const now = new Date('2026-10-29T09:00:00Z');
    expect(backendTokenExpiresAt(now).toISOString()).toBe('2026-10-29T17:00:00.000Z');
  });
});

describe('mintBackendToken', () => {
  const now = new Date('2026-10-29T09:00:00Z');
  const key = new Uint8Array(Buffer.from(BACKEND_JWT_SECRET, 'base64'));

  it('makes an HS256 token that verifies with the secret and carries role, sub, tid and exp', async () => {
    vi.stubEnv('BACKEND_JWT_SECRET', BACKEND_JWT_SECRET);
    const token = await mintBackendToken({ oid: OID_ADVISOR, role: 'lead', tenantId: TENANT_A }, now);

    const { payload, protectedHeader } = await jwtVerify(token, key, {
      algorithms: ['HS256'],
      currentDate: now,
    });
    expect(protectedHeader.alg).toBe('HS256');
    expect(payload.sub).toBe(OID_ADVISOR);
    expect(payload.role).toBe('lead');
    expect(payload.tid).toBe(TENANT_A);
    expect(payload.services).toEqual([]);
    expect(payload.exp).toBe(Math.floor(now.getTime() / 1000) + 8 * 3600);
  });

  it('carries exactly sub, role, services, tid, iat and exp: no name, no email, nothing else', async () => {
    vi.stubEnv('BACKEND_JWT_SECRET', BACKEND_JWT_SECRET);
    const token = await mintBackendToken({ oid: OID_ADVISOR, role: 'advisor', tenantId: TENANT_A }, now);
    const { payload } = await jwtVerify(token, key, { currentDate: now });
    expect(Object.keys(payload).sort()).toEqual(['exp', 'iat', 'role', 'services', 'sub', 'tid']);
  });

  it('does not verify with another secret, and is dead eight hours later', async () => {
    vi.stubEnv('BACKEND_JWT_SECRET', BACKEND_JWT_SECRET);
    const token = await mintBackendToken({ oid: OID_ADVISOR, role: 'advisor', tenantId: TENANT_A }, now);
    await expect(jwtVerify(token, new Uint8Array(32).fill(1), { currentDate: now })).rejects.toThrow();
    await expect(jwtVerify(token, key, { currentDate: new Date(now.getTime() + 8 * 3600_000 + 1000) })).rejects.toThrow();
  });

  it.each([
    ['missing', undefined],
    ['empty', ''],
    ['not base64 of 32 bytes', 'too-short'],
    ['16 bytes', Buffer.alloc(16, 1).toString('base64')],
  ])('refuses to mint when the secret is %s, naming the variable and not its value', async (_name, value) => {
    vi.stubEnv('BACKEND_JWT_SECRET', value as string);
    const attempt = mintBackendToken({ oid: OID_ADVISOR, role: 'advisor', tenantId: TENANT_A }, now);
    await expect(attempt).rejects.toThrow('BACKEND_JWT_SECRET');
    if (value) await expect(attempt).rejects.not.toThrow(value);
  });

  it('refuses a tenant id that is not a tenant id, so the claim is never a free-form value', async () => {
    vi.stubEnv('BACKEND_JWT_SECRET', BACKEND_JWT_SECRET);
    for (const tenantId of ['', 'Trust A', 'net-abcdef', 'a', '../x', 'x'.repeat(40)]) {
      await expect(mintBackendToken({ oid: OID_ADVISOR, role: 'advisor', tenantId }, now)).rejects.toThrow();
    }
  });

  it('refuses an object id that is not a GUID', async () => {
    vi.stubEnv('BACKEND_JWT_SECRET', BACKEND_JWT_SECRET);
    await expect(mintBackendToken({ oid: 'person@example.test', role: 'advisor', tenantId: TENANT_A }, now)).rejects.toThrow();
  });
});

describe('safeNext', () => {
  it('keeps a same-origin path', () => {
    expect(safeNext('/case/4821', 'advisor')).toBe('/case/4821');
    expect(safeNext('/lead?tab=late', 'lead')).toBe('/lead?tab=late');
  });

  it.each(['https://evil.example', '//evil', '/\\evil', 'javascript:alert(1)', '', 'lead'])(
    'sends %j to the role home',
    (next) => {
      expect(safeNext(next, 'advisor')).toBe('/advisor');
      expect(safeNext(next, 'owner')).toBe('/owner/criteria');
    },
  );

  it('sends nothing, null and undefined to the role home', () => {
    expect(safeNext(undefined, 'clinical')).toBe('/clinical');
    expect(safeNext(null, 'lead')).toBe('/lead');
  });

  it('sends a path the role may not open to the role home', () => {
    expect(safeNext('/lead', 'advisor')).toBe('/advisor');
    expect(safeNext('/console', 'lead')).toBe('/lead');
    expect(safeNext('/advisor/case/4821', 'lead')).toBe('/advisor/case/4821');
  });

  it('does not send a signed-in person back to the sign-in page', () => {
    expect(safeNext('/sign-in?next=%2Flead', 'lead')).toBe('/lead');
    expect(safeNext('/sign-in', 'lead')).toBe('/lead');
  });
});
