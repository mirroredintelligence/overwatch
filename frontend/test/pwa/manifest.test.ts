import { readFileSync } from 'node:fs';
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
    expect(manifest.name).toBe('DIUCS capacity');
    expect(manifest.short_name).toBe('DIUCS');
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
});
