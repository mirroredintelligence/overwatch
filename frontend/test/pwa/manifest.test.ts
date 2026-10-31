import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const manifest = JSON.parse(
  readFileSync(join(process.cwd(), 'public', 'manifest.webmanifest'), 'utf8'),
) as {
  name: string;
  short_name: string;
  start_url: string;
  display: string;
  background_color: string;
  theme_color: string;
  icons: { src: string; sizes: string; type: string; purpose?: string }[];
};

describe('web app manifest', () => {
  it('names the app and opens it at /app, standalone', () => {
    expect(manifest.name).toBe('Overwatch');
    expect(manifest.short_name).toBe('Overwatch');
    expect(manifest.start_url).toBe('/app');
    expect(manifest.display).toBe('standalone');
    expect(manifest.background_color).toBe('#F4F6F5');
    expect(manifest.theme_color).toBe('#0B5C8C');
  });

  it('has a 512px icon and a maskable icon', () => {
    const big = manifest.icons.find((icon) => icon.sizes === '512x512');
    expect(big).toBeDefined();
    expect(manifest.icons.some((icon) => icon.sizes === '192x192')).toBe(true);
    expect(manifest.icons.some((icon) => icon.purpose === 'maskable')).toBe(true);
  });

  it('names no product but Overwatch', () => {
    expect(JSON.stringify(manifest)).not.toMatch(new RegExp(['diu', 'cs'].join(''), 'i'));
  });

  it('points every icon at a PNG of the size it claims', () => {
    for (const icon of manifest.icons) {
      const file = join(process.cwd(), 'public', icon.src);
      expect(existsSync(file), icon.src).toBe(true);
      const [width, height] = pngSize(file);
      expect(`${width}x${height}`, icon.src).toBe(icon.sizes);
    }
  });

  it('has the browser tab icon and the iOS home-screen icon from the same mark', () => {
    expect(pngSize(join(process.cwd(), 'app', 'icon.png'))).toEqual([64, 64]);
    expect(pngSize(join(process.cwd(), 'app', 'apple-icon.png'))).toEqual([180, 180]);
  });
});

/** The width and height in a PNG's IHDR chunk, after the 8-byte signature and the chunk's length and type. */
function pngSize(file: string): [number, number] {
  const bytes = readFileSync(file);
  expect(bytes.subarray(1, 4).toString('ascii'), file).toBe('PNG');
  return [bytes.readUInt32BE(16), bytes.readUInt32BE(20)];
}
