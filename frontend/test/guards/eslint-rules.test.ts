// @vitest-environment node
import { fileURLToPath } from 'node:url';
import { ESLint } from 'eslint';
import { describe, expect, it } from 'vitest';

// The lint rules that keep tenant and caching mistakes out as they are typed (TEN-048). The repository
// scans (no-caching, no-literals) are the net; these are the editor-time warning. Each rule is shown
// to fire on a sample that breaks it, and to stay quiet in the one file that is allowed to.

const ROOT = fileURLToPath(new URL('../..', import.meta.url));
const eslint = new ESLint({ cwd: ROOT });

async function messages(code: string, file: string): Promise<string[]> {
  const [result] = await eslint.lintText(code, { filePath: `${ROOT}${file}` });
  return (result?.messages ?? []).map((m) => m.message);
}
const has = (found: string[], word: string) => found.some((m) => m.includes(word));

describe('browser storage', () => {
  it.each([
    'export function f() { return localStorage.getItem("a"); }',
    'export function f() { return window.localStorage.getItem("a"); }',
    'export function f() { return globalThis.localStorage; }',
    'export function f() { return sessionStorage.length; }',
    'export function f() { return indexedDB.open("x"); }',
  ])('forbids %s outside the helper', async (code) => {
    expect(has(await messages(code, 'lib/board/x.ts'), 'tenantStore')).toBe(true);
  });

  it('lets the store, the sign-out and the telemetry session id use it', async () => {
    const code = 'export function f() { return window.localStorage.length + sessionStorage.length; }';
    for (const file of ['lib/storage/tenantStore.ts', 'lib/session/signOut.ts', 'lib/telemetry/events.ts']) {
      expect(has(await messages(code, file), 'tenantStore'), file).toBe(false);
    }
  });

  it('forbids writing document.cookie from the page', async () => {
    expect(has(await messages('export function f() { document.cookie = "a=b"; }', 'components/x/Y.tsx'), 'cookie')).toBe(true);
    expect(has(await messages('export function f() { return document.cookie; }', 'components/x/Y.tsx'), 'cookie')).toBe(false);
  });
});

describe('framework caches', () => {
  it('forbids the use cache directive', async () => {
    expect(has(await messages("'use cache';\nexport default function P() { return null; }", 'app/page.tsx'), 'cache')).toBe(true);
  });

  it('forbids unstable_cache, cacheLife and cacheTag', async () => {
    for (const name of ['unstable_cache', 'cacheLife', 'cacheTag']) {
      expect(has(await messages(`import { ${name} } from 'next/cache';\nexport const x = ${name};`, 'lib/x.ts'), 'cache'), name).toBe(true);
    }
  });

  it('forbids a revalidate export and a force-static or error dynamic', async () => {
    expect(has(await messages('export const revalidate = 60;', 'app/page.tsx'), 'revalidate')).toBe(true);
    expect(has(await messages("export const dynamic = 'force-static';", 'app/page.tsx'), 'dynamic')).toBe(true);
    expect(has(await messages("export const dynamic = 'error';", 'app/page.tsx'), 'dynamic')).toBe(true);
    expect(has(await messages("export const dynamic = 'force-dynamic';", 'app/page.tsx'), 'dynamic')).toBe(false);
  });
});

describe('tenant configuration and headers', () => {
  it('forbids a public environment variable', async () => {
    expect(has(await messages('export const v = process.env.NEXT_PUBLIC_SUPPORT_SHARING;', 'lib/x.ts'), 'NEXT_PUBLIC')).toBe(true);
    expect(has(await messages('export const v = process.env.SESSION_SECRET;', 'lib/x.ts'), 'NEXT_PUBLIC')).toBe(false);
  });

  it('forbids setting a tenant, scope or network header', async () => {
    for (const name of ['X-Tenant-Id', 'x-scope', 'X-Network']) {
      expect(has(await messages(`export function f(h: Headers) { h.set('${name}', 'a'); }`, 'lib/x.ts'), 'header'), name).toBe(true);
    }
    expect(has(await messages("export function f(h: Headers) { h.set('Accept', 'a'); }", 'lib/x.ts'), 'header')).toBe(false);
  });
});

describe('server modules in components', () => {
  it.each(["'next/headers'", "'@/lib/fhir/client'", "'@/lib/auth/session'", "'@/lib/links/server'", "'@/lib/tenant/profile'", "'@/lib/secrets'", "'@/lib/secrets/client'", "'@/lib/webhooks/forward'"])(
    'forbids a component importing %s',
    async (module) => {
      expect(has(await messages(`import * as m from ${module};\nexport const x = m;`, 'components/x/Y.tsx'), 'server')).toBe(true);
    },
  );

  it('lets a page import them, and a component import a type', async () => {
    expect(has(await messages("import { getSession } from '@/lib/auth/session';\nexport const x = getSession;", 'app/x/page.tsx'), 'server')).toBe(false);
    expect(has(await messages("import type { Session } from '@/lib/auth/session';\nexport type X = Session;", 'components/x/Y.tsx'), 'server')).toBe(false);
  });
});

// Linting the whole application takes about two minutes on a loaded machine: the budget is generous so this guard cannot flake.
describe('what is left alone', () => {
  it('has no rule that fires on the application as it stands', async () => {
    const results = await eslint.lintFiles(['app/**/*.{ts,tsx}', 'components/**/*.{ts,tsx}', 'lib/**/*.{ts,tsx}', 'proxy.ts']);
    const own = results.flatMap((r) => r.messages.map((m) => `${r.filePath}: ${m.message}`));
    expect(own).toEqual([]);
  }, 600_000);

  it('does not apply to tests, which may name what the rules forbid', async () => {
    expect(await messages('export const a = localStorage;\nexport const b = process.env.NEXT_PUBLIC_X;', 'lib/x.test.ts')).toEqual([]);
  });
});
