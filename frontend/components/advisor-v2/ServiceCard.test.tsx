import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { capacityToOption, type CapacityService } from '@/lib/advisor/v2/overview';
import { ServiceCard } from './parts';

// The service card in the grid of a region's services (DEC-1381): name and state, group, the figure large with its unit,
// and a foot line. Neutral words only.

const NOW = Date.parse('2026-11-10T22:00:00Z');

function row(over: Partial<CapacityService> = {}): CapacityService {
  return {
    serviceId: 'svc-a',
    name: 'Alpha Team',
    category: 'virtual-beds',
    status: 'accepting',
    effectiveAvailable: 4,
    overBy: null,
    unitLabel: 'beds free',
    reportedAt: '2026-11-10T21:10:00Z',
    figureUnavailable: false,
    lastFigure: 4,
    nextDueAt: null,
    districts: [],
    area: null,
    ...over,
  };
}

const card = (over: Partial<CapacityService> = {}) => <ServiceCard option={capacityToOption(row(over), NOW)} now={NOW} />;

describe('ServiceCard', () => {
  it('is one link to the service with the name, the state as a word, the group, the figure and when it was updated', () => {
    render(card());
    const link = screen.getByRole('link', { name: 'Alpha Team, Accepting, 4 beds free' });
    expect(link).toHaveAttribute('href', '/advisor/v2/services/svc-a');
    expect(link).toHaveTextContent('Alpha Team');
    expect(link).toHaveTextContent('Accepting');
    expect(link).toHaveTextContent('Virtual beds');
    expect(link).toHaveTextContent('4');
    expect(link).toHaveTextContent('beds free');
    expect(link).toHaveTextContent('Updated 50 min ago');
  });

  it('says "Current capacity unavailable" and gives the last figure, never a number as current, when the figure is not current', () => {
    render(card({ figureUnavailable: true, effectiveAvailable: null, lastFigure: 5, unitLabel: 'slots left today', reportedAt: '2026-11-10T13:00:00Z' }));
    const link = screen.getByRole('link', { name: /Alpha Team, Accepting, Current capacity unavailable/ });
    expect(link).toHaveTextContent('Current capacity unavailable');
    expect(link).toHaveTextContent(/Last reported: 5 slots left today/);
    expect(link).not.toHaveTextContent('Updated');
  });

  it('says when an out-of-hours service reopens, and only when the data holds that time', () => {
    const { rerender } = render(card({ status: 'out-of-hours', nextDueAt: '2026-11-11T08:00:00Z' }));
    expect(screen.getByRole('link')).toHaveTextContent('Out of hours');
    expect(screen.getByRole('link')).toHaveTextContent('Reopens 08:00 tomorrow');
    rerender(card({ status: 'out-of-hours', nextDueAt: null }));
    expect(screen.getByRole('link')).not.toHaveTextContent('Reopens');
    // A service that is open has a next-due time too: it is not a reopening time.
    rerender(card({ status: 'accepting', nextDueAt: '2026-11-11T08:00:00Z' }));
    expect(screen.getByRole('link')).not.toHaveTextContent('Reopens');
  });

  it('shows the amount above normal for a service over capacity', () => {
    render(card({ status: 'over-capacity', overBy: 3, effectiveAvailable: null }));
    expect(screen.getByRole('link', { name: 'Alpha Team, Over capacity, +3 above normal' })).toBeInTheDocument();
  });

  it('has no accessibility violations', async () => {
    const { container } = render(
      <ul>
        <li>{card()}</li>
        <li>{card({ serviceId: 'svc-b', figureUnavailable: true, effectiveAvailable: null })}</li>
      </ul>,
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
