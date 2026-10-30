import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { SITE_URL } from './support/env';

// The reporter's installable app and its PIN screen in a real browser, at phone width (W32, W34,
// W35). Written, not run: the orchestrator runs the e2e suite once at the end of the bundle.

async function noHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

test.describe('reporter app at phone width (390 CSS px)', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('the manifest is linked, and the offline page says there is no connection', async ({ page }) => {
    await page.goto(`${SITE_URL}/offline`);
    await expect(page.getByRole('heading', { name: 'No connection' })).toBeVisible();
    await noHorizontalScroll(page);
    const manifest = await page.request.get(`${SITE_URL}/manifest.webmanifest`);
    expect(manifest.ok()).toBe(true);
    expect((await manifest.json()).display).toBe('standalone');
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toEqual([]);
  });

  test('the PIN keypad is named, keyboard-operable, and passes axe', async ({ page }) => {
    await page.goto(`${SITE_URL}/app/pin`);
    await expect(page.getByRole('heading', { name: 'Enter your PIN' })).toBeVisible();
    await page.getByRole('button', { name: '1' }).focus();
    await page.keyboard.press('Enter');
    await expect(page.getByRole('status')).toHaveText('1 of 6 digits entered');
    await page.getByRole('button', { name: 'Delete' }).press('Enter');
    await expect(page.getByRole('status')).toHaveText('0 of 6 digits entered');
    await noHorizontalScroll(page);
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toEqual([]);
  });
});
