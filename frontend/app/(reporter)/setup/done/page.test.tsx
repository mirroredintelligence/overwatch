import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import SetupDonePage from './page';

describe('set-up done page', () => {
  it('says the reporter is set up and when they will be contacted, for text', async () => {
    const { container } = render(await SetupDonePage({ searchParams: Promise.resolve({ channel: 'text' }) }));
    expect(screen.getByRole('heading', { level: 1, name: 'You are set up' })).toBeInTheDocument();
    expect(screen.getByText('We will contact you at your usual time.')).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
