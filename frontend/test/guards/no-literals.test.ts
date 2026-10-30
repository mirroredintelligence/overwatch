// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { check, FETCH_ALLOWLIST, LITERAL_RULES, sourceFiles } from './scan';

// Repository scan: nothing in the app names a place, an organisation type, a system or a phone number
// of its own; nothing reads tenant configuration from a build-time or public environment variable;
// nothing touches browser storage except the one helper; nothing calls the back end except the one
// client (TEN-048, audit D 5 and 9). Wording and numbers come from the tenant's profile and policy
// (TEN-049). Every rule has a sample that breaks it and the repository has no violation.

const ids = (rule: string, text: string, file = 'app/page.tsx') =>
  check(LITERAL_RULES.filter((r) => r.id === rule), [{ file, text }]).map((v) => v.rule);

describe('the literal rules fire on what they forbid', () => {
  it.each([
    ['place-name', 'const title = "Dorset urgent care";'],
    ['place-name', '<h1>dorset capacity</h1>'],
    ['trust-wording', '<p>Use your Trust staff account</p>'],
    ['trust-wording', 'Sign in with your Trust account'],
    ['spoa', '<p>Phone the SPOA shift lead</p>'],
    ['single-point', 'Single point of access'],
    ['epr-name', 'Summary for SystmOne'],
    ['example-domain', 'https://diucs.example/b4821'],
    ['area-code', 'Call 01305 123456'],
    ['public-env', 'const v = process.env.NEXT_PUBLIC_SUPPORT_SHARING;'],
    ['retired-env', 'process.env.SPOA_PHONE_DISPLAY'],
    ['retired-env', 'process.env.BACKEND_JWT_SECRET'],
    ['retired-env', 'DIUCS_ENTRA_BINDINGS'],
    ['retired-env', 'process.env.ENTRA_TENANT_ID'],
    ['direct-storage', 'window.localStorage.setItem("a", "b")'],
    ['direct-storage', 'indexedDB.open("x")'],
    ['session-storage', 'sessionStorage.setItem("a", "b")'],
    ['cookie-write', 'document.cookie = "a=b";'],
    ['cache-api', 'const c = await caches.open("pages");'],
    ['backend-base-url', 'process.env.DIUCS_FHIR_BASE_URL'],
    ['node-http', "import http from 'node:http';"],
    ['node-http', "import { request } from 'https';"],
    ['fetch-call', 'await fetch("https://elsewhere.example/x");'],
    ['tenant-header-set', "headers.set('X-Tenant-Id', id);"],
    ['tenant-header-set', 'headers.append("x-scope", "network");'],
    ['console-secret', 'console.log("token", token);'],
    ['console-secret', 'console.warn(`cookie ${cookie}`)'],
    ['console-secret', 'console.error(idToken)'],
  ])('%s: %s', (rule, text) => {
    expect(ids(rule, text)).toEqual([rule]);
  });

  it('forbids a client component importing a server module', () => {
    for (const imported of ["'@/lib/fhir/client'", "'@/lib/auth/session'", "'@/lib/links/server'", "'@/lib/tenant/profile'", "'next/headers'", "'node:crypto'"]) {
      const text = `'use client';\nimport { x } from ${imported};\n`;
      expect(ids('client-imports-server', text, 'components/x/Y.tsx'), imported).toEqual(['client-imports-server']);
    }
  });

  it('lets a client component import a type from a server module, and a server component import anything', () => {
    expect(ids('client-imports-server', "'use client';\nimport type { Session } from '@/lib/auth/session';\n", 'components/x/Y.tsx')).toEqual([]);
    expect(ids('client-imports-server', "import { getSession } from '@/lib/auth/session';\n", 'app/page.tsx')).toEqual([]);
  });

  it('allows the helpers their own storage and back-end access, and nobody else', () => {
    expect(ids('direct-storage', 'window.localStorage', 'lib/storage/tenantStore.ts')).toEqual([]);
    expect(ids('direct-storage', 'window.localStorage', 'lib/session/signOut.ts')).toEqual([]);
    expect(ids('direct-storage', 'window.localStorage', 'lib/board/x.ts')).toEqual(['direct-storage']);
    expect(ids('session-storage', 'sessionStorage.getItem("a")', 'lib/telemetry/events.ts')).toEqual([]);
    expect(ids('backend-base-url', 'process.env.DIUCS_FHIR_BASE_URL', 'lib/fhir/client.ts')).toEqual([]);
    expect(ids('backend-base-url', 'process.env.DIUCS_FHIR_BASE_URL', 'lib/board/x.ts')).toEqual(['backend-base-url']);
    expect(ids('node-http', "import http from 'node:http';", 'lib/fhir/hostCall.ts')).toEqual([]);
    expect(ids('node-http', "import http from 'node:http';", 'lib/links/server.ts')).toEqual(['node-http']);
  });

  it('allows a fetch only in the files that are named for it, and a new one fails until it is named', () => {
    for (const file of Object.keys(FETCH_ALLOWLIST)) expect(ids('fetch-call', 'await fetch(url);', file), file).toEqual([]);
    expect(ids('fetch-call', 'await fetch(url);', 'lib/new/thing.ts')).toEqual(['fetch-call']);
    expect(ids('fetch-call', 'await fetch(url);', 'app/api/bff/new/route.ts')).toEqual(['fetch-call']);
  });

  it('names a reason for every allowed fetch', () => {
    for (const [file, reason] of Object.entries(FETCH_ALLOWLIST)) expect(reason.length, file).toBeGreaterThan(10);
  });

  it('leaves alone words that only look like a violation', () => {
    for (const [rule, text] of [
      ['place-name', 'const dorsetLike = 1;'],
      ['spoa', 'const spoaless = 1;'],
      ['public-env', 'const PUBLIC = 1;'],
      ['console-secret', 'console.warn("staff sign-in refused: state")'],
      ['cookie-write', 'const header = document.cookie;'],
      ['cookie-write', 'if (document.cookie === "") return;'],
      ['direct-storage', 'const storageKey = 1;'],
      ['tenant-header-set', "headers.set('Accept', 'x');"],
    ] as const) {
      expect(ids(rule, text), `${rule}: ${text}`).toEqual([]);
    }
  });

  it('does not look at tests, fixtures or end-to-end files', () => {
    for (const file of ['lib/x.test.ts', 'test/fixtures/x.ts', 'e2e/x.spec.ts']) {
      expect(check(LITERAL_RULES, [{ file, text: 'Dorset Trust account SPOA NEXT_PUBLIC_X fetch(u)' }]), file).toEqual([]);
    }
  });
});

describe('the repository', () => {
  const files = sourceFiles();

  it('names no place, organisation type, system or phone number of its own, reads no tenant configuration from the environment, touches no browser storage but its helper, and calls the back end from one client only', () => {
    expect(check(LITERAL_RULES, files)).toEqual([]);
  });

  it('has the one client that may call the back end', () => {
    const calling = files.filter((f) => /DIUCS_FHIR_BASE_URL/.test(f.text)).map((f) => f.file).sort();
    expect(calling.every((f) => f.startsWith('lib/fhir/'))).toBe(true);
    expect(calling.length).toBeGreaterThan(0);
  });
});
