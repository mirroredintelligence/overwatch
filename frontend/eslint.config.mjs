import nextVitals from 'eslint-config-next/core-web-vitals';
import nextTs from 'eslint-config-next/typescript';
import { defineConfig, globalIgnores } from 'eslint/config';

// Guard rails for tenancy and caching (TEN-048). They warn as the mistake is typed; the repository
// scans in test/guards are the net that fails the build. Both say the same things:
//
//   - browser storage goes through lib/storage/tenantStore (nothing personal in the browser);
//   - nothing opts into a framework cache (use cache, unstable_cache, revalidate, force-static);
//   - tenant configuration is never read from a public environment variable, and no tenant, scope or
//     network is ever set as a header;
//   - a component (which may run in the browser) does not import a server module.
//
// Tests, fixtures and end-to-end files are left alone: they name what the rules forbid.

const STORAGE_MESSAGE = 'Use lib/storage/tenantStore: browser storage holds interface state only, per host, and is wiped on sign-out (TEN-050).';
const GLOBALS = ['localStorage', 'sessionStorage', 'indexedDB'];

const storageSyntax = [
  { selector: `MemberExpression[property.name=/^(${GLOBALS.join('|')})$/]`, message: STORAGE_MESSAGE },
];

const commonSyntax = [
  {
    selector: "MemberExpression[object.object.name='process'][object.property.name='env'][property.name=/^NEXT_PUBLIC_/]",
    message: 'No NEXT_PUBLIC variable: it is built into the page for every tenant. Tenant wording and numbers come from the profile (TEN-049).',
  },
  {
    selector: "ExportNamedDeclaration > VariableDeclaration > VariableDeclarator[id.name='revalidate']",
    message: 'No revalidate export: nothing in the app is cached or static (TEN-048).',
  },
  {
    selector: "ExportNamedDeclaration > VariableDeclaration > VariableDeclarator[id.name='dynamic'][init.value=/^(force-static|error)$/]",
    message: "No force-static or error dynamic: every page is rendered per request, so use dynamic = 'force-dynamic' (TEN-048).",
  },
  {
    selector: "ExpressionStatement[directive=/^use cache/]",
    message: 'No use cache: a framework cache would show one tenant\'s answer to another (TEN-048).',
  },
  {
    selector: "AssignmentExpression[left.object.name='document'][left.property.name='cookie']",
    message: 'Cookies are set by the server only; the page never writes document.cookie.',
  },
  {
    selector: "CallExpression[callee.property.name=/^(set|append)$/][arguments.0.value=/^x-?(tenant|scope|network)/i]",
    message: 'Never send a tenant, scope or network as a header: the tenant is the signed token (DEC-130, DEC-134).',
  },
];

const cacheImports = {
  paths: [
    {
      name: 'next/cache',
      importNames: ['unstable_cache', 'cacheLife', 'cacheTag'],
      message: 'No framework cache: it would show one tenant\'s answer to another (TEN-048).',
    },
  ],
};

const serverOnly = [
  { group: ['next/headers'], message: 'This is a server module: a component may run in the browser. Read it in a page or route and pass props.', allowTypeImports: true },
  { group: ['@/lib/fhir/*', '@/lib/auth/session', '@/lib/auth/oidc', '@/lib/secrets', '@/lib/secrets/*', '@/lib/webhooks/*', '@/lib/links/server', '@/lib/tenant/profile'], message: 'This is a server module: a component may run in the browser. Read it in a page or route and pass props.', allowTypeImports: true },
];

export default defineConfig([
  ...nextVitals,
  ...nextTs,
  globalIgnores([
    '.next/**',
    'out/**',
    'node_modules/**',
    'playwright-report/**',
    'test-results/**',
    'next-env.d.ts',
  ]),
  {
    // Application source.
    files: ['app/**/*.{ts,tsx}', 'components/**/*.{ts,tsx}', 'lib/**/*.{ts,tsx}', 'proxy.ts'],
    ignores: ['**/*.test.{ts,tsx}'],
    rules: {
      'no-restricted-globals': ['error', ...GLOBALS.map((name) => ({ name, message: STORAGE_MESSAGE }))],
      'no-restricted-syntax': ['error', ...storageSyntax, ...commonSyntax],
      'no-restricted-imports': ['error', cacheImports],
    },
  },
  {
    // The files that may touch browser storage: the helper, the sign-out that wipes it, and the
    // telemetry session id (per tab, not linked to a person).
    files: ['lib/storage/tenantStore.ts', 'lib/session/signOut.ts', 'lib/telemetry/events.ts'],
    rules: {
      'no-restricted-globals': 'off',
      'no-restricted-syntax': ['error', ...commonSyntax],
    },
  },
  {
    // Components may run in the browser.
    files: ['components/**/*.{ts,tsx}'],
    ignores: ['**/*.test.{ts,tsx}'],
    rules: {
      'no-restricted-imports': ['error', { ...cacheImports, patterns: serverOnly }],
    },
  },
]);
