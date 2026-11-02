// Renders the Overwatch wordmark (public/brand/overwatch-logo.svg) to a PNG for email:
//
//   public/brand/overwatch-logo-email.png   1040 x 240, transparent, shown at 208 x 48 in the email
//
// Most mail apps do not show SVG, so the email carries this PNG, served from the web app (the email's
// <img> points at /brand/overwatch-logo-email.png). Run from frontend/:  node scripts/generate-email-logo.mjs
// It uses the Chromium Playwright already installs. The PNG is committed; the build does not run this.

import { readFile, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from '@playwright/test';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const svg = await readFile(join(root, 'public/brand/overwatch-logo.svg'), 'utf8');
const dataUri = `data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}`;

const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 520, height: 120 }, deviceScaleFactor: 2 });
  await page.setContent(`<style>html,body{margin:0;background:transparent}</style><img src="${dataUri}" width="520" height="120" alt="">`);
  const png = await page.screenshot({ omitBackground: true, clip: { x: 0, y: 0, width: 520, height: 120 } });
  await writeFile(join(root, 'public/brand/overwatch-logo-email.png'), png);
  console.log('public/brand/overwatch-logo-email.png', png.length, 'bytes');
} finally {
  await browser.close();
}
