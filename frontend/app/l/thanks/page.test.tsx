// @vitest-environment node
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { sealThanks } from '@/lib/links/thanks';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { RECORDED_ANSWER } from '@/test/fixtures/links';
import ThanksPage, { dynamic, metadata } from './page';

// The thank-you page after a figure is recorded (KI-179). Its address holds no link token (the link is
// spent), and the detail it shows is sealed by the BFF, so a hand-made address cannot make the page say a
// figure was recorded.

beforeEach(() => vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET));

async function thanks(query: Record<string, string | string[] | undefined>): Promise<string> {
  const element = await ThanksPage({ searchParams: Promise.resolve(query) });
  return renderToStaticMarkup(element as React.ReactElement).replace(/<[^>]+>/g, '|');
}

describe('the thank-you page', () => {
  it('says what was recorded, when, and when the next update is due, from a sealed detail', async () => {
    const text = await thanks({ d: await sealThanks(RECORDED_ANSWER) });
    expect(text).toContain('Thank you');
    expect(text).toContain('UCR West: 3 referrals in the next 2 hrs, recorded at 10:12.');
    expect(text).toContain('Next update due 12:00');
    expect(text).toContain('See the live board');
    expect(text).toContain('You can close this page.');
  });

  it('says thank you and claims nothing was recorded when the address carries no sealed detail', async () => {
    const text = await thanks({});
    expect(text).toContain('Thank you');
    expect(text).not.toMatch(/recorded at/);
    expect(text).toContain('You can close this page.');
  });

  it('claims nothing for an address made by hand in the old form', async () => {
    const text = await thanks({ serviceName: 'UCR West', value: '4', unit: 'referrals in the next 2 hrs', at: '2026-10-23T09:12:00Z' });
    expect(text).not.toMatch(/UCR West|recorded at/);
  });

  it('claims nothing for a detail that is not sealed with this key, or has been changed', async () => {
    const sealed = await sealThanks(RECORDED_ANSWER);
    expect(await thanks({ d: `${sealed.slice(0, -4)}AAAA` })).not.toMatch(/recorded at/);
  });

  it('claims nothing, and does not fail, when there is no secret to open it with', async () => {
    const sealed = await sealThanks(RECORDED_ANSWER);
    vi.stubEnv('SESSION_SECRET', '');
    const text = await thanks({ d: sealed });
    expect(text).toContain('Thank you');
    expect(text).not.toMatch(/recorded at/);
  });

  it('takes the first value when the address names the detail twice', async () => {
    expect(await thanks({ d: ['not-a-sealed-value', await sealThanks(RECORDED_ANSWER)] })).not.toMatch(/recorded at/);
  });

  it('asks the browser not to send the address as a referrer, and is never cached', () => {
    expect(metadata).toMatchObject({ referrer: 'no-referrer' });
    expect(dynamic).toBe('force-dynamic');
  });
});
