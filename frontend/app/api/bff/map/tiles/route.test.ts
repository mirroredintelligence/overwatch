// @vitest-environment node
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { leadRequest } from '@/test/lead-session';
import { GET } from './route';

vi.mock('next/headers', async () => ({ cookies: (await import('@/test/cookies')).cookiesMock }));

// The map's tile route (DEC-1362): one byte range of the tile file, for a signed-in person only.

const URL_ = 'https://app.test/api/bff/map/tiles';
let dir = '';
let file = '';

beforeAll(() => {
  dir = mkdtempSync(join(tmpdir(), 'tiles-route-'));
  file = join(dir, 'tiles.pmtiles');
  writeFileSync(file, Buffer.from(Array.from({ length: 64 }, (_, index) => index)));
});
afterAll(() => rmSync(dir, { recursive: true, force: true }));

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('NODE_ENV', 'production');
});
afterEach(() => vi.unstubAllEnvs());

async function asked(role: 'advisor' | null, range: string | null): Promise<Response> {
  const base = await leadRequest(URL_, role);
  const headers = new Headers(base.headers);
  if (range !== null) headers.set('Range', range);
  return GET(new Request(base.url, { headers }));
}

describe('GET /api/bff/map/tiles', () => {
  it('answers the bytes asked for with 206 and the range and size', async () => {
    vi.stubEnv('OVERWATCH_MAP_TILES_FILE', file);
    const response = await asked('advisor', 'bytes=4-7');
    expect(response.status).toBe(206);
    expect(response.headers.get('Content-Range')).toBe('bytes 4-7/64');
    expect(Array.from(new Uint8Array(await response.arrayBuffer()))).toEqual([4, 5, 6, 7]);
    expect(response.headers.get('Cache-Control')).toMatch(/no-store/);
  });

  it('refuses a person who is not signed in, without reading the file', async () => {
    vi.stubEnv('OVERWATCH_MAP_TILES_FILE', file);
    expect((await asked(null, 'bytes=0-3')).status).toBe(401);
  });

  it('refuses a range that is open, missing or too long', async () => {
    vi.stubEnv('OVERWATCH_MAP_TILES_FILE', file);
    expect((await asked('advisor', 'bytes=0-')).status).toBe(416);
    expect((await asked('advisor', null)).status).toBe(416);
    expect((await asked('advisor', 'bytes=0-99999999')).status).toBe(416);
  });

  it('answers not found when no tile file is configured, so the page keeps its schematic', async () => {
    vi.stubEnv('OVERWATCH_MAP_TILES_FILE', '');
    vi.stubEnv('OVERWATCH_MAP_TILES_URL', '');
    const response = await asked('advisor', 'bytes=0-3');
    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ code: 'no-tiles' });
  });

  it('answers a fixed error, not the cause, when the file cannot be read', async () => {
    vi.stubEnv('OVERWATCH_MAP_TILES_FILE', join(dir, 'missing.pmtiles'));
    const response = await asked('advisor', 'bytes=0-3');
    expect(response.status).toBe(502);
    expect(await response.text()).not.toMatch(/ENOENT|missing/);
  });
});
