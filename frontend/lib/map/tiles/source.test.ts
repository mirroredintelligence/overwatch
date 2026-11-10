// @vitest-environment node
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { readTileRange, tilesConfigured } from './source';

let dir = '';
let file = '';

beforeAll(() => {
  dir = mkdtempSync(join(tmpdir(), 'tiles-'));
  file = join(dir, 'tiles.pmtiles');
  writeFileSync(file, Buffer.from(Array.from({ length: 100 }, (_, index) => index)));
});

afterAll(() => rmSync(dir, { recursive: true, force: true }));

describe('the tile source (DEC-1362)', () => {
  it('is configured by a blob URL or a local file, and by nothing else', () => {
    expect(tilesConfigured({})).toBe(false);
    expect(tilesConfigured({ OVERWATCH_MAP_TILES_URL: '' })).toBe(false);
    expect(tilesConfigured({ OVERWATCH_MAP_TILES_URL: 'https://x/y' })).toBe(true);
    expect(tilesConfigured({ OVERWATCH_MAP_TILES_FILE: file })).toBe(true);
  });

  it('reads the bytes asked for from a local file, and the file size', async () => {
    const result = await readTileRange({ start: 10, end: 14 }, { OVERWATCH_MAP_TILES_FILE: file });
    expect(result.status).toBe(206);
    expect(Array.from(result.body ?? [])).toEqual([10, 11, 12, 13, 14]);
    expect(result.total).toBe(100);
  });

  it('stops at the end of the file, and answers not found past it', async () => {
    const end = await readTileRange({ start: 98, end: 200 }, { OVERWATCH_MAP_TILES_FILE: file });
    expect(Array.from(end.body ?? [])).toEqual([98, 99]);
    const past = await readTileRange({ start: 100, end: 120 }, { OVERWATCH_MAP_TILES_FILE: file });
    expect(past.status).toBe(404);
  });

  it('answers not found when nothing is configured', async () => {
    expect((await readTileRange({ start: 0, end: 1 }, {})).status).toBe(404);
  });
});
