import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { WORKER_URL } from '@/components/map/TileMap';
import { ATTRIBUTION, mapStyle, TILES_PATH } from './style';

const root = join(__dirname, '..', '..');

describe('the map style (DEC-1362)', () => {
  const style = mapStyle('https://app.test');

  it('reads tiles and glyphs from the app origin only, so the CSP needs no new source', () => {
    expect(style.glyphs).toBe('https://app.test/map/fonts/{fontstack}/{range}.pbf');
    const source = style.sources.os as { url: string; attribution: string };
    expect(source.url).toBe(`pmtiles://https://app.test${TILES_PATH}`);
    expect(source.attribution).toBe(ATTRIBUTION);
    expect(JSON.stringify(style)).not.toMatch(/https?:\/\/(?!app\.test)/);
  });

  it('names the OS licence line the map shows', () => {
    expect(ATTRIBUTION).toMatch(/Contains OS data .* Crown copyright and database right/);
  });

  it('uses only fonts that are served, with the glyph ranges for Latin text', () => {
    const fonts = new Set<string>();
    for (const layer of style.layers) {
      const font = (layer as { layout?: { 'text-font'?: string[] } }).layout?.['text-font'];
      font?.forEach((name) => fonts.add(name));
    }
    expect(fonts.size).toBeGreaterThan(0);
    for (const name of fonts) {
      for (const range of ['0-255', '256-511', '8192-8447']) {
        expect(existsSync(join(root, 'public', 'map', 'fonts', name, `${range}.pbf`)), `${name} ${range}`).toBe(true);
      }
    }
  });

  it('serves the worker of the installed MapLibre version from public/map', () => {
    const wanted = (JSON.parse(readFileSync(join(root, 'package.json'), 'utf8')) as { dependencies: Record<string, string> }).dependencies['maplibre-gl'];
    const worker = readFileSync(join(root, 'public', WORKER_URL), 'utf8').slice(0, 400);
    expect(worker).toContain(`/v${wanted}/`);
  });
});
