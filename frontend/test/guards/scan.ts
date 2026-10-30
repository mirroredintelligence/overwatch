import { readdirSync, readFileSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

// The repository scans behind test/guards/no-caching.test.ts and no-literals.test.ts (TEN-048). A rule
// is a name, a reason, the files it looks at and a test of the text; `check` runs rules over files and
// names each violation by rule, file and line. The scans read the application source only: not tests,
// fixtures, end-to-end files or generated code.

export type SourceFile = { file: string; text: string };
export type Rule = {
  id: string;
  why: string;
  appliesTo: (file: string) => boolean;
  /** Line numbers (1-based) of the violations in `text`. */
  lines: (text: string, file: string) => number[];
};
export type Violation = { rule: string; file: string; line: number };

const ROOT = fileURLToPath(new URL('../..', import.meta.url));
const DIRECTORIES = ['app', 'components', 'lib'];
const ROOT_FILES = ['proxy.ts', 'next.config.ts'];
const SOURCE = /\.(ts|tsx)$/;

function walk(directory: string, found: string[]): void {
  for (const name of readdirSync(`${ROOT}${directory}`)) {
    const path = `${directory}/${name}`;
    if (statSync(`${ROOT}${path}`).isDirectory()) walk(path, found);
    else found.push(path);
  }
}

/** Application source: the three source directories and the two root files, tests and fixtures left out. */
export function isSource(file: string): boolean {
  if (!SOURCE.test(file)) return false;
  if (/\.(test|spec)\.(ts|tsx)$/.test(file)) return false;
  if (/^(test|e2e|node_modules|\.next)\//.test(file)) return false;
  return DIRECTORIES.some((d) => file.startsWith(`${d}/`)) || ROOT_FILES.includes(file);
}

export function sourceFiles(): SourceFile[] {
  const found: string[] = [];
  for (const directory of DIRECTORIES) walk(directory, found);
  found.push(...ROOT_FILES);
  return found.filter(isSource).sort().map((file) => ({ file, text: readFileSync(`${ROOT}${file}`, 'utf8') }));
}

export function check(rules: Rule[], files: SourceFile[]): Violation[] {
  const found: Violation[] = [];
  for (const { file, text } of files) {
    if (!isSource(file)) continue;
    for (const rule of rules) {
      if (!rule.appliesTo(file)) continue;
      for (const line of rule.lines(text, file)) found.push({ rule: rule.id, file, line });
    }
  }
  return found;
}

/** The lines of `text` that match a pattern, as a list of line numbers. */
function matching(pattern: RegExp): (text: string) => number[] {
  return (text) => {
    const lines: number[] = [];
    text.split('\n').forEach((line, index) => {
      if (pattern.test(line)) lines.push(index + 1);
    });
    return lines;
  };
}

const everywhere = () => true;
const except = (...files: string[]) => (file: string) => !files.includes(file);

// ----------------------------------------------------------------------------------------------
// Caching

const NEXT_CONFIG = (file: string) => file === 'next.config.ts';

export const CACHING_RULES: Rule[] = [
  {
    id: 'use-cache-directive',
    why: 'the use cache directive keeps an answer in a framework cache shared across requests',
    appliesTo: everywhere,
    lines: matching(/^\s*['"]use cache(:\s*\w+)?['"]\s*;?\s*$/),
  },
  { id: 'unstable-cache', why: 'unstable_cache keeps data across requests', appliesTo: everywhere, lines: matching(/\bunstable_cache\b/) },
  { id: 'cache-life-tag', why: 'cacheLife and cacheTag are the controls of the use cache cache', appliesTo: everywhere, lines: matching(/\b(cacheLife|cacheTag)\b/) },
  { id: 'revalidate-export', why: 'a revalidate export makes a route static for a time', appliesTo: everywhere, lines: matching(/^\s*export\s+(const|let|var)\s+revalidate\b/) },
  {
    id: 'force-static',
    why: 'a force-static or error dynamic makes a route static',
    appliesTo: everywhere,
    lines: matching(/^\s*export\s+const\s+dynamic\s*=\s*['"](force-static|error)['"]/),
  },
  { id: 'fetch-cache-export', why: 'a fetchCache export sets how every fetch of a route is cached', appliesTo: everywhere, lines: matching(/^\s*export\s+const\s+fetchCache\b/) },
  {
    id: 'fetch-next-options',
    why: 'a fetch with next.revalidate or next.tags is stored by the data cache',
    appliesTo: everywhere,
    lines: matching(/next:\s*\{[^}]*\b(revalidate|tags)\b/),
  },
  {
    id: 'fetch-force-cache',
    why: 'a fetch that asks for the cache is stored',
    appliesTo: everywhere,
    lines: matching(/cache:\s*['"](force-cache|only-if-cached)['"]/),
  },
  {
    id: 'cache-components',
    why: 'cache components and partial prerendering turn on the framework cache',
    appliesTo: NEXT_CONFIG,
    lines: matching(/\b(cacheComponents|ppr|useCache|dynamicIO)\b/),
  },
];

// ----------------------------------------------------------------------------------------------
// Literals, environment, storage, the back end

const STORAGE_FILES = ['lib/storage/tenantStore.ts', 'lib/session/signOut.ts'];
const SESSION_STORAGE_FILES = ['lib/telemetry/events.ts', 'lib/session/signOut.ts'];

/** The files that call `fetch`, and why each may. A new file that calls it fails until it is named here. */
export const FETCH_ALLOWLIST: Record<string, string> = {
  'lib/advisor/browser.ts': 'the advisor pages\' browser helper: its callers pass /api/bff paths',
  'lib/advisor/useBooking.ts': 'the booking hook passes the browser\'s fetch to its BFF calls',
  'lib/bff/browser.ts': 'the browser helper for the BFF\'s JSON routes (a path under /api/bff)',
  'lib/screens/client.ts': 'the wall pairing pages\' browser client: its callers pass /api/bff/screens paths',
  'lib/fhir/client.ts': 'the one server-side client of the back end FHIR API (token required, no cache, no tenant)',
  'lib/auth/oidc.ts': 'the staff sign-in redeems its code at the identity provider, not at the back end',
  'app/api/bff/telemetry/route.ts': 'forwards a batch of interface events to the telemetry collector, not to the back end',
  'lib/board/client.ts': 'the browser reads the board from its own BFF route',
  'lib/board/useBoardFeed.ts': 'the browser refreshes the board from its own BFF route',
  'lib/telemetry/events.ts': 'the browser sends interface events to its own BFF telemetry route',
  'lib/links/browser.ts': 'the link page calls its own BFF link routes',
  'lib/session/signOut.ts': 'sign-out calls the BFF session route',
};

// A `fetch(` whose first argument is written out as an /api/bff path is a call to the app's own BFF
// from the browser and needs no entry; any other `fetch(` (a variable address) must be named above.
function fetchOutsideBff(text: string): number[] {
  const lines: number[] = [];
  for (const match of text.matchAll(/\bfetch\s*\(\s*/g)) {
    const after = text.slice((match.index ?? 0) + match[0].length, (match.index ?? 0) + match[0].length + 12);
    if (/^[`'"]\/api\/bff\//.test(after)) continue;
    lines.push(text.slice(0, match.index).split('\n').length);
  }
  return lines;
}

function clientImportsServer(text: string): number[] {
  if (!/^\s*['"]use client['"]/m.test(text)) return [];
  const server = /^import\s+(?!type\b)[^;]*?from\s+['"](@\/lib\/(fhir|auth\/session|links\/server|tenant\/profile)(\/[^'"]*)?|next\/headers|node:[a-z/]+)['"]/gm;
  const lines: number[] = [];
  for (const match of text.matchAll(server)) lines.push(text.slice(0, match.index).split('\n').length);
  return lines;
}

export const LITERAL_RULES: Rule[] = [
  { id: 'place-name', why: 'a place name is the tenant\'s own (its profile), never a literal', appliesTo: everywhere, lines: matching(/\bDorset\b/i) },
  { id: 'trust-wording', why: 'not every tenant is a trust; the sign-in wording is "staff account"', appliesTo: everywhere, lines: matching(/\bTrust (staff )?account\b/i) },
  { id: 'spoa', why: 'the coordination team has the tenant\'s own name (its profile)', appliesTo: everywhere, lines: matching(/\bSPOA\b/) },
  { id: 'single-point', why: 'the coordination team has the tenant\'s own name (its profile)', appliesTo: everywhere, lines: matching(/single point of access/i) },
  { id: 'epr-name', why: 'the referral system is the tenant\'s own word (its profile)', appliesTo: everywhere, lines: matching(/SystmOne/i) },
  {
    id: 'example-domain',
    why: 'a link or sender address is the tenant\'s own host (FHIR code-system addresses are the platform\'s, and are not links)',
    appliesTo: except('lib/fhir/codes.ts', 'lib/advisor/case-fhir.ts'),
    lines: matching(/diucs\.example/),
  },
  { id: 'area-code', why: 'a phone number is the tenant\'s own (its profile)', appliesTo: everywhere, lines: matching(/\b01305\b/) },
  { id: 'public-env', why: 'a NEXT_PUBLIC variable is built into the page for every tenant', appliesTo: everywhere, lines: matching(/NEXT_PUBLIC_/) },
  {
    id: 'retired-env',
    why: 'these variables were global settings or signing secrets; the profile and the back end replaced them',
    appliesTo: everywhere,
    lines: matching(/\b(SPOA_PHONE_DISPLAY|SUPPORT_SHARING|BACKEND_JWT_SECRET|DIUCS_ENTRA_BINDINGS|ENTRA_TENANT_ID)\b/),
  },
  { id: 'direct-storage', why: 'browser storage goes through lib/storage/tenantStore', appliesTo: except(...STORAGE_FILES), lines: matching(/\b(localStorage|indexedDB)\b/) },
  { id: 'session-storage', why: 'browser storage goes through lib/storage/tenantStore (the telemetry session id aside)', appliesTo: except(...SESSION_STORAGE_FILES), lines: matching(/\bsessionStorage\b/) },
  { id: 'cookie-write', why: 'cookies are set by the server only', appliesTo: everywhere, lines: matching(/document\.cookie\s*=[^=]/) },
  { id: 'cache-api', why: 'nothing is put in Cache Storage but static assets, and not by the application', appliesTo: everywhere, lines: matching(/\bcaches\s*\.\s*(open|put|add|addAll)\b/) },
  {
    id: 'backend-base-url',
    why: 'the back end address is read by lib/fhir only',
    appliesTo: (file) => !file.startsWith('lib/fhir/'),
    lines: matching(/DIUCS_FHIR_BASE_URL/),
  },
  {
    id: 'node-http',
    why: 'the one place that sends a Host header to the back end is lib/fhir/hostCall.ts',
    appliesTo: except('lib/fhir/hostCall.ts'),
    lines: matching(/from\s+['"](node:)?https?['"]/),
  },
  {
    id: 'fetch-call',
    why: 'a call to anywhere but an /api/bff path is named in FETCH_ALLOWLIST with its reason',
    appliesTo: (file) => !(file in FETCH_ALLOWLIST),
    lines: fetchOutsideBff,
  },
  { id: 'tenant-header-set', why: 'no tenant, scope or network is ever sent as a header', appliesTo: everywhere, lines: matching(/\.(set|append)\(\s*['"]x-?(tenant|scope|network)/i) },
  {
    id: 'console-secret',
    why: 'a token, secret, cookie or password is never logged',
    appliesTo: everywhere,
    lines: matching(/console\.\w+\([^)]*\b(token|secret|cookie|password|idToken|authorization)\b/i),
  },
  { id: 'client-imports-server', why: 'a client component must not import a server module', appliesTo: everywhere, lines: clientImportsServer },
];

// ----------------------------------------------------------------------------------------------
// The ratchet. Code that was built before these rules existed still breaks some of them (a place name
// or a referral system written into a screen's words, a browser storage call in the tour and the
// learning progress). Those are listed here, per file and per rule, with how many. The scan fails on
// anything not listed and on anything listed that is no longer there, so the table only shrinks: fix
// a file and lower its count in the same change. Each belongs to the screen's tenancy rework (the
// words from the profile, TEN-049 and the screens' tasks).

export const DEBT: Record<string, Record<string, number>> = {
  'app/api/bff/cases/[ref]/summary/route.ts': { 'epr-name': 1 },
  'components/advisor/BookingCard.tsx': { 'epr-name': 2 },
  'components/advisor/OptionsList.tsx': { 'epr-name': 1 },
  'components/advisor/SummaryCopy.tsx': { 'epr-name': 2 },
  'components/advisor/WithdrawalAlert.tsx': { 'spoa': 1 },
  'components/exec/EscalationForm.tsx': { 'spoa': 2 },
  'components/help/SafetyConcernForm.tsx': { 'spoa': 2 },
  'components/learn/HelpPanel.tsx': { 'spoa': 2 },
  'components/planning/PlanningView.tsx': { 'spoa': 1, 'trust-wording': 1 },
  'components/reporter/BookingChange.tsx': { 'epr-name': 1, 'spoa': 9 },
  'components/reporter/BookingDecision.tsx': { 'epr-name': 2, 'spoa': 4 },
  'lib/advisor/summary.ts': { 'epr-name': 1 },
  'lib/links/model.ts': { 'spoa': 2 },
  'lib/tour/content.ts': { 'epr-name': 1, 'spoa': 4 },
};

export type RatchetResult = { unlisted: Violation[]; stale: string[] };

/** Violations that are not in the debt table, and debt entries that are no longer true. */
export function ratchet(found: Violation[], debt: Record<string, Record<string, number>> = DEBT): RatchetResult {
  const counts = new Map<string, number>();
  for (const v of found) counts.set(`${v.file}|${v.rule}`, (counts.get(`${v.file}|${v.rule}`) ?? 0) + 1);
  const allowed = new Map<string, number>();
  for (const [file, rules] of Object.entries(debt)) for (const [rule, n] of Object.entries(rules)) allowed.set(`${file}|${rule}`, n);

  const unlisted: Violation[] = [];
  const seen = new Map<string, number>();
  for (const v of found) {
    const key = `${v.file}|${v.rule}`;
    const used = (seen.get(key) ?? 0) + 1;
    seen.set(key, used);
    if (used > (allowed.get(key) ?? 0)) unlisted.push(v);
  }
  const stale: string[] = [];
  for (const [key, n] of allowed) {
    const actual = counts.get(key) ?? 0;
    if (actual < n) stale.push(`${key}: listed ${n}, found ${actual}`);
  }
  return { unlisted, stale };
}
