import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, test } from '@playwright/test';
import { signIn } from './support/session';
import { SITE_URL } from './support/env';
import { TOKEN_ORG_A } from './support/tokens';

// Screenshots of the main staff pages for design reviews (DEC-1365). Sample data only, from the stand-in back end.
// Runs only with DESIGN_SHOT_DIR set (a folder relative to frontend/), for example
// DESIGN_SHOT_DIR=../docs/delivery/evidence/DEC-1365-shots/before DESIGN_SHOT_PREFIX=before pnpm exec playwright test design-shots
const DIR = process.env.DESIGN_SHOT_DIR;
const HERE = fileURLToPath(new URL('.', import.meta.url));

test.skip(DIR === undefined, 'set DESIGN_SHOT_DIR to take screenshots');
test.describe.configure({ mode: 'serial' });

test('main staff pages', async ({ page }) => {
  const out = resolve(HERE, '..', DIR ?? 'test-results/design-shots');
  mkdirSync(out, { recursive: true });
  await page.setViewportSize({ width: 1280, height: 900 });
  const shot = (name: string) => page.screenshot({ path: resolve(out, `${name}.png`), fullPage: true });

  await signIn(page.context(), SITE_URL, 'advisor', TOKEN_ORG_A);
  await page.goto('/advisor');
  await expect(page.getByRole('heading', { name: 'Ready for calls' })).toBeVisible();
  await shot('advisor-home');

  await page.goto('/advisor/board');
  await expect(page.locator('[data-el="WALL-TILE"]').first()).toBeVisible();
  await shot('board');

  // The board again with reduced motion: the pulse stops and the glow is a static ring at full strength.
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/advisor/board');
  await expect(page.locator('[data-el="WALL-TILE"]').first()).toBeVisible();
  await shot('board-reduced-motion');
  console.log('attention on the board:', await page.locator('[data-attention]').evaluateAll((els) => els.map((e) => `${e.getAttribute('data-service-id')}:${e.getAttribute('data-attention')}`)));
  await page.emulateMedia({ reducedMotion: 'no-preference' });

  await page.goto('/advisor');
  await page.getByRole('button', { name: 'Start a new call' }).click();
  await expect(page).toHaveURL(/\/advisor\/case\/case-1$/);
  await page.locator('[data-el="ADV-NEEDS-REFERRER-AMBULANCE"]').click();
  await page.locator('[data-el="ADV-NEEDS-AGE-80PLUS"]').click();
  await page.getByLabel('Where is the patient? Postcode').fill('DT4 8XX');
  await page.locator('[data-el="ADV-NEEDS-NEED-FRAILTY"]').click();
  await page.locator('[data-el="ADV-NEEDS-URGENCY-WITHIN-2-HRS"]').click();
  await page.locator('[data-el="ADV-NEEDS-CONTINUE-BTN"]').click();
  await expect(page).toHaveURL(/\/options$/);
  await expect(page.locator('[data-el="ADV-OPT-CARD"]').first()).toBeVisible();
  await shot('options-list');

  await signIn(page.context(), SITE_URL, 'lead', TOKEN_ORG_A);
  await page.goto('/lead');
  await expect(page.getByRole('main')).toBeVisible();
  await shot('lead-overview');

  // The wall board: it must not change with the tightening pass (DEC-1365), so it is shot with the others.
  await signIn(page.context(), SITE_URL, 'wall', TOKEN_ORG_A);
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.goto('/screen');
  await expect(page.locator('[data-el="WALL-TILE"]').first()).toBeVisible();
  await shot('wall-screen');
});
