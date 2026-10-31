import { describe, expect, it } from 'vitest';
import { canAccess, isSamePathOnly, roleHome, rolesFor } from './access';
import { ROLES, type Role } from './session';

// Which role may open which path prefix (W09 "Rules you need"). The proxy and the
// sign-in's "where to go next" both read this one table.

const TABLE: [string, Role[]][] = [
  ['/advisor', ['advisor']],
  ['/advisor/case', ['advisor']],
  ['/advisor/case/4821', ['advisor']],
  ['/clinical', ['clinical']],
  ['/lead', ['lead']],
  ['/owner', ['owner', 'clinical']],
  ['/owner/criteria', ['owner', 'clinical']],
  // W30: the criteria pages live at /criteria/<service> (route group (owner)); the owner, the clinical lead and the shift lead may open them.
  ['/criteria', ['owner', 'clinical', 'lead']],
  ['/criteria/s1', ['owner', 'clinical', 'lead']],
  ['/criteria/s1/history', ['owner', 'clinical', 'lead']],
  ['/planning', ['exec', 'lead']],
  // W9H: the executive's alerts on their phone sit under /planning; the page itself sends a lead on to the home screen.
  ['/planning/phone', ['exec', 'lead']],
  ['/console', ['support']],
  // The tenant administrator's pages (TEN-076).
  ['/admin', ['tenant-admin']],
  ['/admin/config', ['tenant-admin']],
  ['/admin/support', ['tenant-admin']],
  // The network administrator's pages (TEN-080): the owner's own role; no other role, the tenant
  // administrator included, opens them, and the network pages are not for it.
  ['/network-admin', ['network-admin']],
  ['/network-admin/grants', ['network-admin']],
  ['/network-admin/listings', ['network-admin']],
  // The operator console is a different door (lib/operator/access.ts): no TENANT role opens it.
  ['/operator', []],
  ['/operator/tenants/trust-a', []],
];

describe('rolesFor', () => {
  it.each(TABLE)('%s may be opened by %j', (path, roles) => {
    expect([...(rolesFor(path) ?? [])].sort()).toEqual([...roles].sort());
  });

  it.each(['/', '/screen', '/screen/pair', '/sign-in', '/forbidden', '/case/4821', '/api/bff/board', '/advisors', '/leader', '/consoles', '/criteriaa', '/administrator', '/operators'])(
    'leaves %s unguarded',
    (path) => {
      expect(rolesFor(path)).toBeNull();
    },
  );

  it.each([
    ['capitals', '/Lead'],
    ['a trailing slash', '/lead/'],
    ['a percent-encoded letter', '/%6Cead'],
    ['an encoded slash', '/x%2F..%2Flead'],
    ['a doubled slash', '//lead'],
    ['a dot segment', '/x/../lead'],
    ['a dot', '/./lead'],
  ])('still guards a path written with %s', (_name, path) => {
    expect(rolesFor(path)).toEqual(['lead']);
  });

  it('guards a path with capitals past the first letter', () => {
    expect([...(rolesFor('/ADVISOR/case') ?? [])].sort()).toEqual(['advisor']);
  });

  it('lets nobody in when the path cannot be decoded', () => {
    expect(rolesFor('/%E0%A4%A')).toEqual([]);
    expect(canAccess('lead', '/%E0%A4%A')).toBe(false);
  });
});

describe('canAccess', () => {
  const guarded = TABLE.map(([path]) => path);

  it.each(ROLES.flatMap((role) => guarded.map((path) => [role, path] as const)))(
    '%s on %s agrees with the table',
    (role, path) => {
      const allowed = TABLE.find(([p]) => p === path)![1];
      expect(canAccess(role, path)).toBe(allowed.includes(role));
    },
  );

  it('lets every role open an unguarded path', () => {
    for (const role of ROLES) expect(canAccess(role, '/screen')).toBe(true);
  });
});

describe('roleHome', () => {
  it.each([
    ['advisor', '/advisor'],
    ['clinical', '/clinical'],
    ['lead', '/lead'],
    ['owner', '/owner/criteria'],
    ['exec', '/planning'],
    ['support', '/console'],
    ['tenant-admin', '/admin'],
    ['network-admin', '/network-admin'],
  ] as [Role, string][])('sends %s to %s', (role, home) => {
    expect(roleHome(role)).toBe(home);
  });

  it('sends a role that has no staff page to the front page', () => {
    for (const role of ['reporter', 'wall', 'anonymous-link', 'audit'] as Role[]) expect(roleHome(role)).toBe('/');
  });

  it('can open its own home, whichever role', () => {
    for (const role of ['advisor', 'clinical', 'lead', 'owner', 'exec', 'support', 'tenant-admin', 'network-admin'] as Role[]) {
      expect(canAccess(role, roleHome(role))).toBe(true);
    }
  });
});

describe('isSamePathOnly', () => {
  it.each(['/case/4821', '/lead', '/lead?tab=late', '/advisor/case/4821?x=1#top', '/'])('accepts %s', (value) => {
    expect(isSamePathOnly(value)).toBe(true);
  });

  it.each([
    '',
    'case/4821',
    'https://evil.example',
    '//evil.example',
    '/\\evil.example',
    '/\\\\evil',
    'javascript:alert(1)',
    ' /lead',
    '/lead\r\nSet-Cookie: x=1',
    '/\t/evil.example',
    '/\u0000lead',
    '/' + 'a'.repeat(2100),
  ])('refuses %j', (value) => {
    expect(isSamePathOnly(value)).toBe(false);
  });
});

describe('a next path for a tenant role', () => {
  it('is never the operator console, whatever the role', () => {
    for (const role of ROLES) {
      expect(canAccess(role, '/operator'), role).toBe(false);
      expect(canAccess(role, '/operator/audit'), role).toBe(false);
      expect(canAccess(role, '/OPERATOR/tenants'), role).toBe(false);
    }
  });
});
