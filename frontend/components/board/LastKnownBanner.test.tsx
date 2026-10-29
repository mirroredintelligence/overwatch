import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { Assessment } from '@/lib/board/liveness';
import { runAxe } from '@/test/a11y';
import { LastKnownBanner } from './LastKnownBanner';

type LastKnown = Extract<Assessment, { mode: 'last-known' }>;

function lastKnown(over: Partial<LastKnown> = {}): LastKnown {
  return {
    mode: 'last-known',
    reason: 'offline',
    since: '2026-10-23T13:02:00Z',
    asOf: '2026-10-23T13:02:00Z',
    now: '2026-10-23T13:12:00Z',
    ageMs: 600_000,
    ...over,
  };
}

describe('LastKnownBanner', () => {
  it('says in words that the tool is offline, since when, and what to do', () => {
    render(<LastKnownBanner lastKnown={lastKnown()} />);

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('Tool offline since 14:02');
    expect(alert).toHaveTextContent('Figures are the last known and may be wrong. Use the whiteboard and phone process.');
  });

  it('is the only alert, and its text does not change as the clock moves (so it is announced once)', () => {
    const { rerender } = render(<LastKnownBanner lastKnown={lastKnown()} />);
    const before = screen.getByRole('alert').textContent;

    rerender(<LastKnownBanner lastKnown={lastKnown({ now: '2026-10-23T13:42:00Z', ageMs: 2_400_000 })} />);

    expect(screen.getAllByRole('alert')).toHaveLength(1);
    expect(screen.getByRole('alert').textContent).toBe(before);
  });

  it('says when the figures were last refreshed and how long ago, outside the alert', () => {
    render(<LastKnownBanner lastKnown={lastKnown()} />);

    const line = screen.getByText(/Board last refreshed 14:02/);
    expect(line).toHaveTextContent('Board last refreshed 14:02 · 10 min ago');
    expect(screen.getByRole('alert')).not.toContainElement(line);
  });

  it('gives the age to the minute, and in hours when it is long', () => {
    render(<LastKnownBanner lastKnown={lastKnown({ now: '2026-10-23T15:07:00Z', ageMs: 7_500_000 })} />);

    expect(screen.getByText(/Board last refreshed/)).toHaveTextContent('2 hrs 5 min ago');
  });

  it('shows London time across the autumn clock change: 00:59 UTC is 01:59 BST, and 01:02 UTC is 01:02 GMT', () => {
    render(
      <LastKnownBanner
        lastKnown={lastKnown({ since: '2026-10-25T00:59:00Z', asOf: '2026-10-25T00:59:00Z', now: '2026-10-25T01:02:30Z', ageMs: 210_000 })}
      />,
    );

    expect(screen.getByRole('alert')).toHaveTextContent('Tool offline since 01:59');
    expect(screen.getByText(/Board last refreshed/)).toHaveTextContent('Board last refreshed 01:59 · 3 min ago');
  });

  it('uses the first failure time for the offline time and the board time for the refreshed time', () => {
    render(
      <LastKnownBanner
        lastKnown={lastKnown({ since: '2026-10-23T13:04:00Z', asOf: '2026-10-23T13:02:00Z' })}
      />,
    );

    expect(screen.getByRole('alert')).toHaveTextContent('Tool offline since 14:04');
    expect(screen.getByText(/Board last refreshed/)).toHaveTextContent('14:02');
  });

  it('has a stable element id for tests and has no axe violations', async () => {
    const { container } = render(<LastKnownBanner lastKnown={lastKnown()} />);

    expect(container.querySelector('[data-el="WALL-OFFLINE-BANNER"]')).not.toBeNull();
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
