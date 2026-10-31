// Regenerates the app's PNG icons from public/brand/overwatch-mark.svg, the one source of the mark:
//
//   public/icons/icon-192.png            192 x 192, the mark on the page colour
//   public/icons/icon-512.png            512 x 512, the same
//   public/icons/icon-512-maskable.png   512 x 512, full-bleed, the mark inside the maskable safe zone
//   app/icon.png                         64 x 64, the browser tab icon (Next adds the <link rel="icon">)
//   app/apple-icon.png                   180 x 180, the iOS home-screen icon (Next adds the apple-touch-icon)
//
// Run from frontend/:  node scripts/generate-icons.mjs
//
// It renders the SVG with the Chromium that Playwright already installs for the end-to-end tests, so it
// needs no dependency of its own. The PNGs are committed; the build does not run this.

import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from '@playwright/test';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const BACKGROUND = '#F4F6F5'; // --c-bg, the manifest's background_color

// size: the PNG's side. markShare: the mark's width as a share of it. Android masks a maskable icon to a
// circle of 80% of the side, so its mark stays inside that circle (the ring's outer diameter is 110/120 of
// the mark, so 0.66 of the side puts it at 0.605, well inside 0.8).
const ICONS = [
  { file: 'public/icons/icon-192.png', size: 192, markShare: 0.72 },
  { file: 'public/icons/icon-512.png', size: 512, markShare: 0.72 },
  { file: 'public/icons/icon-512-maskable.png', size: 512, markShare: 0.66 },
  { file: 'app/icon.png', size: 64, markShare: 0.84 },
  { file: 'app/apple-icon.png', size: 180, markShare: 0.72 },
];

const mark = await readFile(join(root, 'public/brand/overwatch-mark.svg'), 'utf8');
const markDataUri = `data:image/svg+xml;base64,${Buffer.from(mark).toString('base64')}`;

const browser = await chromium.launch();
try {
  for (const { file, size, markShare } of ICONS) {
    const page = await browser.newPage({ viewport: { width: size, height: size }, deviceScaleFactor: 1 });
    const width = Math.round(size * markShare);
    await page.setContent(
      `<!doctype html><meta charset="utf-8"><style>html,body{margin:0;width:${size}px;height:${size}px;background:${BACKGROUND}}
       body{display:flex;align-items:center;justify-content:center}img{width:${width}px;height:${width}px;display:block}</style>
       <img alt="" src="${markDataUri}">`,
    );
    await page.waitForFunction(() => document.images[0].complete);
    const png = await page.screenshot({ type: 'png', clip: { x: 0, y: 0, width: size, height: size } });
    const target = join(root, file);
    await mkdir(dirname(target), { recursive: true });
    await writeFile(target, png);
    await page.close();
    console.log(`${file}  ${size}x${size}  ${png.length} bytes`);
  }
} finally {
  await browser.close();
}
