// @vitest-environment node
import { describe, expect, it } from 'vitest';
import * as staff from './staff';
import { safeNext } from './staff';

// Staff sign-in rules that do not depend on the provider. The role is the back end's (the tenant's own
// mapping, TEN-043) and the back-end token is the back end's too: this module no longer maps an app
// role, mints a token or reads a signing secret.

describe('what this module no longer does (TEN-044)', () => {
  it('has no way to map an app role, mint a token or name a signing secret', () => {
    expect(Object.keys(staff).sort()).toEqual(['safeNext']);
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
