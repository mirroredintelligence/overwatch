import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { LINK } from '@/test/fixtures/links';
import ThanksPage, { dynamic, metadata } from './page';

async function thanks(token: string, query = '') {
  const params = new URLSearchParams(query);
  const element = await ThanksPage({
    params: Promise.resolve({ token }),
    searchParams: Promise.resolve(Object.fromEntries(params)),
  });
  return render(element as React.ReactElement);
}

const ANSWERED =
  'serviceName=UCR+West&value=4&unit=referrals+in+the+next+2+hrs&at=2026-10-23T09%3A12%3A00Z&next=2026-10-23T11%3A00%3A00Z';

describe('the thank-you page', () => {
  it('says what was recorded, when, and when the next update is due', async () => {
    const { container } = await thanks(LINK.recorded, ANSWERED);
    expect(screen.getByRole('heading', { level: 1, name: 'Thank you' })).toBeInTheDocument();
    expect(screen.getByText('UCR West: 4 referrals in the next 2 hrs, recorded at 10:12.')).toBeInTheDocument();
    expect(screen.getByText('Next update due 12:00')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'See the live board' })).toHaveAttribute('href', '/sign-in');
    expect(screen.getByText('You can close this page.')).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('still says thank you, and shows no figure, when the address carries none', async () => {
    await thanks(LINK.recorded, '');
    expect(screen.getByRole('heading', { level: 1, name: 'Thank you' })).toBeInTheDocument();
    expect(screen.queryByText(/recorded at/)).toBeNull();
    expect(screen.getByText('You can close this page.')).toBeInTheDocument();
  });

  it('shows no figure for an address whose figure is not a whole number from 0 to 999', async () => {
    await thanks(LINK.recorded, ANSWERED.replace('value=4', 'value=1000'));
    expect(screen.queryByText(/recorded at/)).toBeNull();
  });

  it('asks the browser not to send the link address as a referrer', () => {
    expect(metadata).toMatchObject({ referrer: 'no-referrer' });
    expect(dynamic).toBe('force-dynamic');
  });
});
