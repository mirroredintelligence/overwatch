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

// The reporter's flows against the stand-in back end's real route shapes (W8E). Written, not run.
import { EXPIRED_INVITATION, GOOD_CODE, GOOD_INVITATION, GOOD_PIN } from './support/reporter';

test.describe('reporter set-up and sign-in against the back end’s shapes', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('an invitation the back end will not use says it has expired, and a good one goes to set-up', async ({ page }) => {
    await page.goto(`${SITE_URL}/i/${EXPIRED_INVITATION}`);
    await expect(page.getByText('This invitation has expired. Ask the shift lead to send a new one.')).toBeVisible();
    await page.goto(`${SITE_URL}/i/${GOOD_INVITATION}`);
    await expect(page).toHaveURL(/\/setup\?invite=/);
    await expect(page.getByRole('heading', { name: 'Set up capacity reporting for UCR West' })).toBeVisible();
  });

  test('the number step shows the masked number and the code step takes the text code', async ({ page }) => {
    await page.goto(`${SITE_URL}/setup?step=number&invite=${GOOD_INVITATION}`);
    await expect(page.getByText('07xxx xxx456')).toBeVisible();
    await page.getByRole('button', { name: 'Send code' }).click();
    await expect(page.getByRole('heading', { name: 'Enter the code' })).toBeVisible();
    const boxes = page.getByRole('textbox');
    await boxes.first().click();
    await page.keyboard.type(GOOD_CODE);
    await page.getByRole('button', { name: 'Check code' }).click();
    await expect(page.getByRole('heading', { name: 'Choose how we contact you' })).toBeVisible();
  });

  test('a right PIN signs in with a token the browser never sees, and the reporter answers a prompt', async ({ page }) => {
    const seen: string[] = [];
    page.on('response', async (response) => {
      if (response.url().includes('/api/bff/')) seen.push(await response.text().catch(() => ''));
    });
    await page.goto(`${SITE_URL}/app/pin`);
    for (const digit of GOOD_PIN) await page.getByRole('button', { name: digit, exact: true }).click();
    await expect(page).toHaveURL(/\/app\/respond\//);
    await page.getByRole('button', { name: 'Yes, still 3' }).click();
    await expect(page.getByRole('heading', { name: 'Thank you' })).toBeVisible();
    // Neither the PIN session nor a token is ever in an answer the browser reads.
    expect(seen.join('\n')).not.toMatch(/e2e-pin-session|eyJ/);
    const cookies = await page.context().cookies();
    expect(cookies.find((c) => c.name === 'diucs_session')?.httpOnly).toBe(true);
  });

  test('a wrong PIN says how many tries are left and signs nobody in', async ({ page }) => {
    await page.goto(`${SITE_URL}/app/pin`);
    for (const digit of '111111') await page.getByRole('button', { name: digit, exact: true }).click();
    await expect(page.getByText('That PIN is not right. 4 tries left.')).toBeVisible();
    expect((await page.context().cookies()).some((c) => c.name === 'diucs_session')).toBe(false);
  });
});
