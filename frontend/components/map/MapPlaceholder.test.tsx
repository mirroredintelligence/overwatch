import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { renderToString } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { MapPlaceholder } from './MapPlaceholder';

// The picture that stands in the map's box while the zoomable map loads (DEC-1371).

const fit = [
  { lat: 50.71, lon: -2.44 },
  { lat: 50.62, lon: -2.46 },
  { lat: 50.8, lon: -2.2 },
];

describe('MapPlaceholder', () => {
  it('says it is loading the map, to a screen reader and in a visible word', () => {
    const html = renderToString(<MapPlaceholder fit={fit} />);
    expect(html).toContain('role="status"');
    expect(html).toContain('aria-busy="true"');
    expect(html).toMatch(/<span[^>]*>Loading the map\.<\/span>/);
    expect(html).toMatch(/data-el="MAP-LOADING-WORD"[^>]*>Loading the map/);
  });

  it('draws the bundled land under pale pins and bars, with no style attribute', () => {
    const html = renderToString(<MapPlaceholder fit={fit} />);
    expect(html).toContain('data-el="ADV-MAP-LAND"');
    expect(html).toMatch(/data-pin/);
    expect(html).not.toMatch(/style=/);
  });

  it('still draws with no place to fit, and without throwing', () => {
    expect(renderToString(<MapPlaceholder fit={[]} />)).toContain('Loading the map.');
  });

  it('stills every movement under reduced motion, and uses tokens only', () => {
    const css = readFileSync(join(__dirname, 'mapPlaceholder.module.css'), 'utf8');
    const reduced = /@media \(prefers-reduced-motion: reduce\)\s*\{[^@]*animation:\s*none/;
    expect(css).toMatch(reduced);
    expect(css).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
  });
});

describe('MapLoadingBox', () => {
  it('stands in for the map while the options are read: labelled, with no land and no preload in a browser without WebGL', async () => {
    const { MapLoadingBox } = await import('./MapLoadingBox');
    const { preloadMap } = await import('./TileMap');
    const html = renderToString(<MapLoadingBox />);
    expect(html).toContain('Loading the map.');
    expect(html).not.toContain('ADV-MAP-LAND');
    expect(() => preloadMap()).not.toThrow();
  });
});
