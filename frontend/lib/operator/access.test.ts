import { describe, expect, it } from 'vitest';
import { operatorAccessFor, operatorHome, safeOperatorNext } from './access';

// Which operator role may open which page of the console (TEN-083), by the path alone. The proxy and the
// sign-in's "where to go next" read this one table, as they read lib/auth/access.ts for a tenant's pages.

describe('operatorAccessFor', () => {
  it.each([
    ['/operator', ['platform-operator', 'support']],
    ['/operator/tenants/new', ['platform-operator']],
    ['/operator/tenants/trust-a', ['platform-operator']],
    ['/operator/audit', ['platform-operator']],
    ['/operator/support', ['support']],
    ['/operator/support/new', ['support']],
    ['/operator/support/tickets/abc', ['support']],
    ['/operator/anything-else', ['platform-operator', 'support']],
  ])('%s may be opened by %j', (path, roles) => {
    expect(operatorAccessFor(path)).toEqual({ kind: 'guarded', roles });
  });

  it('leaves the sign-in page open, and every path that is not the console alone', () => {
    expect(operatorAccessFor('/operator/sign-in')).toEqual({ kind: 'public' });
    for (const path of ['/', '/lead', '/admin', '/operators', '/api/bff/platform/session', '/sign-in']) {
      expect(operatorAccessFor(path), path).toEqual({ kind: 'none' });
    }
  });

  it.each(['/Operator/audit', '/%6Fperator/audit', '//operator/audit', '/operator/', '/x/../operator/audit', '/./operator/audit', '/operator/tenants/../audit'])(
    'still guards %s',
    (path) => {
      expect(operatorAccessFor(path).kind).toBe('guarded');
    },
  );

  it('does not let a dot segment or case turn a guarded page into the public one', () => {
    expect(operatorAccessFor('/operator/support/../sign-in')).toEqual({ kind: 'public' });
    expect(operatorAccessFor('/operator/sign-in/../audit')).toEqual({ kind: 'guarded', roles: ['platform-operator'] });
    expect(operatorAccessFor('/OPERATOR/Sign-In')).toEqual({ kind: 'public' });
  });

  it('lets nobody in when the path cannot be decoded', () => {
    expect(operatorAccessFor('/operator/%E0%A4%A')).toEqual({ kind: 'guarded', roles: [] });
  });
});

describe('operatorHome', () => {
  it('sends the operator to the tenants and the support person to the support requests', () => {
    expect(operatorHome('platform-operator')).toBe('/operator');
    expect(operatorHome('support')).toBe('/operator/support');
  });
});

describe('safeOperatorNext', () => {
  it('keeps a console page the role may open, and otherwise the role’s home', () => {
    expect(safeOperatorNext('/operator/audit', 'platform-operator')).toBe('/operator/audit');
    expect(safeOperatorNext('/operator/audit?after=50', 'platform-operator')).toBe('/operator/audit?after=50');
    expect(safeOperatorNext('/operator/audit', 'support')).toBe('/operator/support');
    expect(safeOperatorNext('/operator/support', 'platform-operator')).toBe('/operator');
    for (const next of [null, undefined, '', '/lead', '/admin', '/', 'https://evil.example/', '//evil.example', '/operator/sign-in', '/operator/sign-in?error=failed']) {
      expect(safeOperatorNext(next, 'platform-operator'), String(next)).toBe('/operator');
    }
  });
});
