import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { FunnelsTab } from './FunnelsTab';

const FUNNEL = {
  name: 'reporter-setup',
  label: 'Reporter set-up',
  steps: [
    { name: 'Link sent', pct: 100, count: 412, suppressed: false },
    { name: 'Link opened', pct: 95, count: 391, suppressed: false, exitElementId: 'L-CODE-INPUT', medianSeconds: 42 },
    { name: 'Code verified', pct: 84, count: 346, suppressed: false },
    { name: 'Tiny step', pct: null, count: null, suppressed: true },
  ],
  split: [
    { channel: 'Text link', pct: 80, suppressed: false },
    { channel: 'Email link', pct: null, suppressed: true },
    { channel: 'App', pct: 60, suppressed: false },
  ],
};

describe('FunnelsTab', () => {
  it('shows fewer than 10 and no bar for a suppressed step', () => {
    const { container } = render(<FunnelsTab funnel={FUNNEL} />);

    const tiny = within(screen.getByRole('list', { name: /funnel steps/i })).getByText('Tiny step').closest('li');
    expect(tiny).toHaveTextContent('fewer than 10');
    expect(tiny?.querySelector('[data-bar]')).toBeNull();
    expect(container.querySelectorAll('[data-bar]')).toHaveLength(3);
  });

  it('gives every shown bar its value as text', () => {
    render(<FunnelsTab funnel={FUNNEL} />);

    expect(screen.getByText('95%')).toBeInTheDocument();
    expect(screen.getByText('84%')).toBeInTheDocument();
  });

  it('names the biggest drop with its points and exit element', () => {
    render(<FunnelsTab funnel={FUNNEL} />);

    expect(screen.getByText(/Biggest drop/)).toHaveTextContent('Link opened to Code verified: 11 points');
  });

  it('shows the split by channel, with a suppressed channel as fewer than 10', () => {
    render(<FunnelsTab funnel={FUNNEL} />);

    const split = screen.getByRole('table', { name: /by channel/i });
    expect(within(split).getByRole('row', { name: /Email link/ })).toHaveTextContent('fewer than 10');
  });

  it('passes vitest-axe', async () => {
    const { container } = render(<FunnelsTab funnel={FUNNEL} />);

    expect(await runAxe(container)).toHaveNoViolations();
  });
});
