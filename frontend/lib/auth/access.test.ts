import { describe, expect, it } from 'vitest';
import { canAccess, isSamePathOnly, roleHome, rolesFor } from './access';
import { ROLES, type Role } from './session';

// Which role may open which path prefix (W09 "Rules you need"). The proxy and the
// sign-in's "where to go next" both read this one table.

const TABLE: [string, Role[]][] = [
  ['/advisor', ['advisor', 'lead']],
  ['/advisor/case', ['advisor', 'lead']],
  ['/advisor/case/4821', ['advisor', 'lead']],
  ['/clinical', ['clinical']],
  ['/lead', ['lead']],
  ['/owner', ['owner', 'clinical']],
  ['/owner/criteria', ['owner', 'clinical']],
  ['/planning', ['exec', 'lead']],
  ['/console', ['support']],
];

describe('rolesFor', () => {
  it.each(TABLE)('%s may be opened by %j', (path, roles) => {
    expect([...(rolesFor(path) ?? [])].sort()).toEqual([...roles].sort());
  });

  it.each(['/', '/screen', '/screen/pair', '/sign-in', '/forbidden', '/case/4821', '/api/bff/board', '/advisors', '/leader', '/consoles'])(
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
    expect([...(rolesFor('/ADVISOR/case') ?? [])].sort()).toEqual(['advisor', 'lead']);
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
  ] as [Role, string][])('sends %s to %s', (role, home) => {
    expect(roleHome(role)).toBe(home);
  });

  it('sends a role that has no staff page to the front page', () => {
    for (const role of ['reporter', 'wall', 'anonymous-link', 'audit'] as Role[]) expect(roleHome(role)).toBe('/');
  });

  it('can open its own home, whichever role', () => {
    for (const role of ['advisor', 'clinical', 'lead', 'owner', 'exec', 'support'] as Role[]) {
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
