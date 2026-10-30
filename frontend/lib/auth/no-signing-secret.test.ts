// @vitest-environment node
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { describe, expect, it } from 'vitest';

// The BFF holds no secret that can sign a back-end token (TEN-043, DEC-522 item 2, hazard H-261): a
// component that could would be able to name any tenant and any role. The back end signs; this
// side holds the person's sign-in, the session key and the Entra client secret, and nothing else.
// A scan of the source, so a later change that brings the secret back fails here.

const ROOT = new URL('../..', import.meta.url).pathname;
const SKIP = new Set(['node_modules', '.next', 'e2e', 'test']);
const SOURCE = /\.(ts|tsx|mjs|js)$/;
const TEST = /\.test\.(ts|tsx)$/;

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return SKIP.has(name) ? [] : sources(path);
    return SOURCE.test(name) && !TEST.test(name) ? [path] : [];
  });
}

describe('the front end holds no signing secret for the back end’s tokens', () => {
  const files = sources(ROOT);

  it('scans the source (a scan of nothing proves nothing)', () => {
    expect(files.length).toBeGreaterThan(40);
  });

  it('names no BACKEND_JWT_SECRET', () => {
    const named = files.filter((file) => readFileSync(file, 'utf8').includes('BACKEND_JWT_SECRET'));
    expect(named.map((file) => relative(ROOT, file))).toEqual([]);
  });

  it('signs no token with jose (SignJWT)', () => {
    const signing = files.filter((file) => /\bSignJWT\b/.test(readFileSync(file, 'utf8')));
    expect(signing.map((file) => relative(ROOT, file))).toEqual([]);
  });
});
