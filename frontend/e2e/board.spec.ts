import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { BOARD_A, BOARD_B } from '@/test/fixtures/board';
import { TOKEN_ORG_A, TOKEN_ORG_B } from './support/tokens';
import { signIn } from './support/session';

// The wall board in a real browser: layout at the sizes the prompt names, axe
// including colour contrast, and the rule that the board is the session's own.
// Screenshots (sample data only) go to test-results/screenshots. The ones kept as
// evidence are made by running with BOARD_SHOT_DIR=../docs/delivery/evidence/W05.

const HERE = fileURLToPath(new URL('.', import.meta.url));
const SHOTS = resolve(HERE, '..', process.env.BOARD_SHOT_DIR ?? 'test-results/screenshots');
mkdirSync(SHOTS, { recursive: true });

const SIZES = [
  { name: 'wall-1920x1080', width: 1920, height: 1080 },
  { name: 'laptop-1280x720', width: 1280, height: 720 },
  { name: 'zoom-200-percent-960x540', width: 960, height: 540 },
  { name: 'tablet-768x1024', width: 768, height: 1024 },
  { name: 'phone-390x844', width: 390, height: 844 },
] as const;

async function openBoard(page: Page, token = TOKEN_ORG_A, role = 'wall') {
  await signIn(page.context(), 'http://localhost:3000', role, token);
  await page.goto('/screen');
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
}

test('shows the board for the paired screen, with a page title and the page language', async ({ page }) => {
  await openBoard(page);

  await expect(page.getByRole('heading', { level: 1, name: 'Dorset urgent care capacity' })).toBeVisible();
  await expect(page.locator('[data-el="WALL-TILE"]')).toHaveCount(9);
  await expect(page).toHaveTitle(/DIUCS capacity/);
  await expect(page.locator('html')).toHaveAttribute('lang', 'en-GB');
  await expect(page.getByText('No patient information on this screen')).toBeVisible();
});

test('goes to /screen/pair when no screen is signed in', async ({ page }) => {
  await page.goto('/screen');

  await expect(page).toHaveURL(/\/screen\/pair$/);
});

test('shows the same board when the address carries another organisation, and never that organisation’s data', async ({
  page,
}) => {
  await openBoard(page, TOKEN_ORG_A);
  await page.goto(`/screen?tenant=${TOKEN_ORG_B}&organisation=Neighbouring&scope=network`);

  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Dorset urgent care capacity');
  const text = await page.locator('body').innerText();
  for (const e of BOARD_B.entries) expect(text).not.toContain(e.name);
});

test('a screen paired to the other organisation shows that board only', async ({ page }) => {
  await openBoard(page, TOKEN_ORG_B);

  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Neighbouring urgent care capacity');
  await expect(page.locator('[data-el="WALL-TILE"]')).toHaveCount(BOARD_B.entries.length);
  const text = await page.locator('body').innerText();
  for (const e of BOARD_A.entries) expect(text).not.toContain(e.name);
});

test('a reporter session is sent to /screen/pair, and so is a token the back end does not know', async ({ page }) => {
  await signIn(page.context(), 'http://localhost:3000', 'reporter', TOKEN_ORG_A);
  await page.goto('/screen');
  await expect(page).toHaveURL(/\/screen\/pair$/);

  await signIn(page.context(), 'http://localhost:3000', 'wall', 'not-a-token-the-back-end-knows');
  await page.goto('/screen');
  await expect(page).toHaveURL(/\/screen\/pair$/);
});

test.describe('wall layout at 1920 by 1080', () => {
  test.use({ viewport: { width: 1920, height: 1080 } });

  test('has three columns, numbers of at least 72px, and fits the screen without scrolling', async ({ page }) => {
    await openBoard(page);

    const lefts = await page
      .locator('[data-el="WALL-TILE"]')
      .evaluateAll((tiles) => [...new Set(tiles.map((t) => Math.round(t.getBoundingClientRect().left)))]);
    expect(lefts).toHaveLength(3);

    const sizes = await page
      .locator('[data-el="WALL-TILE-NUMBER"]')
      .evaluateAll((nodes) => nodes.map((n) => parseFloat(getComputedStyle(n).fontSize)));
    expect(sizes).toHaveLength(9);
    for (const size of sizes) expect(size).toBeGreaterThanOrEqual(72);

    const { scrollHeight, innerHeight } = await page.evaluate(() => ({
      scrollHeight: document.documentElement.scrollHeight,
      innerHeight: window.innerHeight,
    }));
    expect(scrollHeight).toBeLessThanOrEqual(innerHeight);
  });
});

for (const size of SIZES) {
  test.describe(`at ${size.width} by ${size.height}`, () => {
    test.use({ viewport: { width: size.width, height: size.height } });

    test('has no horizontal scroll, passes axe with colour contrast, and is photographed', async ({ page }) => {
      await openBoard(page);

      const { scrollWidth, clientWidth } = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
      }));
      expect(scrollWidth).toBeLessThanOrEqual(clientWidth);

      const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
      expect(results.violations).toEqual([]);

      await page.screenshot({ path: resolve(SHOTS, `board-${size.name}.png`), fullPage: true });
    });
  });
}

test('keeps the same information when the user asks for reduced motion', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await openBoard(page);

  await expect(page.locator('[data-el="WALL-TILE"]')).toHaveCount(9);
  // The stand-in back end builds the board now, so the was-due time is a London time of day.
  await expect(page.getByText(/^Not updated for 4 hrs 10 min · was due \d\d:\d\d$/)).toBeVisible();
});
