import { expect, test } from '@playwright/test';
import { sameOrigin, syntheticTarget } from '@/test/synthetic/guard';

// The reporter loop as a synthetic check (O09), against a deployed test environment: the test hook
// issues a fresh capacity link for the synthetic test service, a reporter opens it and presses
// "Yes, still N", sees the thank-you page, and the wall board shows the update within the
// prompt-to-board budget. The synthetic service is flagged `synthetic`, so analytics and the real
// board leave it out. Nothing here reaches a real person or number.
//
// Skipped, with the reason named, unless the guard passes (e2e/synthetic guard in test/synthetic).

const SERVICE = 'Synthetic test service';
const PROMPT_TO_BOARD_MS = 3000;
const target = syntheticTarget(process.env);

test.describe('reporter loop @synthetic', { tag: '@synthetic' }, () => {
  test.skip(!target.ok, target.ok ? '' : target.reason);

  test('a reporter answers the prompt and the board shows the new time within 3 s', async ({
    browser,
    request,
  }) => {
    if (!target.ok) throw new Error('unreachable: the test is skipped when the guard refuses');

    const hook = await request.post(`${target.backendUrl}/test/synthetic/prompt`, {
      headers: { Authorization: `Bearer ${target.hookToken}`, 'Content-Type': 'application/json' },
      data: {},
    });
    expect(hook.status(), 'the test hook issues a link').toBe(201);
    const { link } = (await hook.json()) as { link: string };
    expect(sameOrigin(link, target.baseUrl), 'the link is on the target, and nowhere else').toBe(true);

    const boardContext = await browser.newContext({ storageState: target.staffState });
    const reporterContext = await browser.newContext();
    try {
      // The board is open before the answer, so the update is seen arriving, not found later.
      const board = await boardContext.newPage();
      await board.goto(`${target.baseUrl}/screen`);
      const tile = board.locator('[data-el="WALL-TILE"]', { hasText: SERVICE });
      await expect(tile).toBeVisible();

      const reporter = await reporterContext.newPage();
      await reporter.goto(link);
      await reporter.getByRole('button', { name: /^Yes, still \d+$/ }).click();
      await expect(reporter.getByRole('heading', { level: 1, name: 'Thank you' })).toBeVisible();

      await expect(tile.getByText('Updated just now')).toBeVisible({ timeout: PROMPT_TO_BOARD_MS });
    } finally {
      await boardContext.close();
      await reporterContext.close();
    }
  });
});
