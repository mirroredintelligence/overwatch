// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { CACHING_RULES, check, sourceFiles } from './scan';

// Repository scan: nothing in the app can opt into a framework cache (TEN-048, audit D R11). A page,
// route or helper that kept an answer for one person and showed it to another tenant's would be a
// cross-tenant leak that no unit test of its logic would find. Every rule has a sample that breaks it
// (so the rule is shown to fire) and the repository has no violation.

const ids = (rule: string, text: string, file = 'app/page.tsx') =>
  check(CACHING_RULES.filter((r) => r.id === rule), [{ file, text }]).map((v) => v.rule);

describe('the caching rules fire on what they forbid', () => {
  it.each([
    ['use-cache-directive', "'use cache'\nexport default function P() { return null }"],
    ['use-cache-directive', '"use cache: remote"\nexport async function f() {}'],
    ['use-cache-directive', "export async function f() {\n  'use cache'\n  return 1\n}"],
    ['unstable-cache', "import { unstable_cache } from 'next/cache';"],
    ['cache-life-tag', "import { cacheLife } from 'next/cache';"],
    ['cache-life-tag', 'cacheTag("x")'],
    ['revalidate-export', 'export const revalidate = 60;'],
    ['revalidate-export', 'export let revalidate = false'],
    ['force-static', "export const dynamic = 'force-static';"],
    ['force-static', 'export const dynamic = "error";'],
    ['fetch-cache-export', "export const fetchCache = 'force-cache';"],
    ['fetch-next-options', "await fetch(url, { next: { revalidate: 30 } });"],
    ['fetch-next-options', "await fetch(url, { next: { tags: ['a'] } });"],
    ['fetch-force-cache', "await fetch(url, { cache: 'force-cache' });"],
    ['fetch-force-cache', 'await fetch(url, { cache: "only-if-cached" });'],
  ])('%s: %s', (rule, text) => {
    expect(ids(rule, text)).toEqual([rule]);
  });

  it('flags the line it is on', () => {
    const found = check(CACHING_RULES, [{ file: 'app/page.tsx', text: 'a\nb\nexport const revalidate = 5;\n' }]);
    expect(found).toEqual([{ rule: 'revalidate-export', file: 'app/page.tsx', line: 3 }]);
  });

  it('forbids a cache-components setting in the Next configuration', () => {
    for (const text of ['cacheComponents: true', 'experimental: { ppr: true }', 'experimental: { useCache: true }', 'experimental: { dynamicIO: true }']) {
      expect(ids('cache-components', text, 'next.config.ts'), text).toEqual(['cache-components']);
    }
  });

  it('leaves alone what is not a cache option', () => {
    for (const [rule, text] of [
      ['revalidate-export', 'const revalidate = 5;'],
      ['revalidate-export', '// export const revalidate = 5 is forbidden'],
      ['force-static', "export const dynamic = 'force-dynamic';"],
      ['fetch-force-cache', "await fetch(url, { cache: 'no-store' });"],
      ['fetch-next-options', 'await fetch(url, { next: {} });'],
      ['use-cache-directive', "const word = 'use cache';\n"],
    ] as const) {
      expect(ids(rule, text), `${rule}: ${text}`).toEqual([]);
    }
  });

  it('does not look at tests, fixtures or end-to-end files', () => {
    const text = "export const revalidate = 5;";
    for (const file of ['lib/x.test.ts', 'test/fixtures/x.ts', 'e2e/x.spec.ts']) {
      expect(check(CACHING_RULES, [{ file, text }]), file).toEqual([]);
    }
  });
});

describe('the repository', () => {
  const files = sourceFiles();

  it('is being scanned: the scan sees the app, the library and the components', () => {
    const names = files.map((f) => f.file);
    for (const expected of ['app/layout.tsx', 'lib/fhir/client.ts', 'components/board/Board.tsx', 'proxy.ts', 'next.config.ts']) {
      expect(names, expected).toContain(expected);
    }
    expect(files.length).toBeGreaterThan(60);
    expect(names.some((n) => n.endsWith('.test.ts') || n.endsWith('.test.tsx') || n.startsWith('test/') || n.startsWith('e2e/'))).toBe(false);
  });

  it('opts into no framework cache anywhere', () => {
    expect(check(CACHING_RULES, files)).toEqual([]);
  });

  it('renders every request: the root layout is force-dynamic', () => {
    const layout = files.find((f) => f.file === 'app/layout.tsx');
    expect(layout?.text).toMatch(/export const dynamic = 'force-dynamic'/);
  });

  it('has an explicit force-dynamic on every page that reads the session or the board', () => {
    const pages = files.filter((f) => /^app\/.*page\.tsx$/.test(f.file) && /\b(getSession|readBoard)\b/.test(f.text));
    expect(pages.length).toBeGreaterThan(0);
    for (const page of pages) expect(page.text, page.file).toMatch(/export const dynamic = 'force-dynamic'/);
  });
});
