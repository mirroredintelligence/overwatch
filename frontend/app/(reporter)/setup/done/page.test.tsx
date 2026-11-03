import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import SetupDonePage from './page';

describe('set-up done page', () => {
  it('says the reporter is set up, that they will be contacted at their usual time, and asks for nothing else, for text', async () => {
    const { container } = render(await SetupDonePage({ searchParams: Promise.resolve({ channel: 'text' }) }));
    expect(screen.getByRole('heading', { level: 1, name: 'You are set up' })).toBeInTheDocument();
    expect(screen.getByText('We will contact you at your usual time.')).toBeInTheDocument();
    expect(screen.getByText('Reply with your number.')).toBeInTheDocument();
    expect(screen.getByText('There is nothing else to do.')).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('asks for no reply for email, and offers no action', async () => {
    render(await SetupDonePage({ searchParams: Promise.resolve({ channel: 'email' }) }));
    expect(screen.getByRole('heading', { level: 1, name: 'You are set up' })).toBeInTheDocument();
    expect(screen.getByText('We will contact you at your usual time.')).toBeInTheDocument();
    expect(screen.queryByText('Reply with your number.')).toBeNull();
    expect(screen.queryAllByRole('link')).toHaveLength(0);
    expect(screen.queryAllByRole('button')).toHaveLength(0);
  });
});
