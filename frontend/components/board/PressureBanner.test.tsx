import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { BOARD_A, BOARD_QUIET, BOARD_SURGE, entry, QUIET_ENTRIES, SURGE_ENTRIES } from '@/test/fixtures/board';
import { PressureBanner } from './PressureBanner';

describe('PressureBanner', () => {
  it('shows "System under pressure" and the count of services when every service in hours is limited or worse', () => {
    render(<PressureBanner board={BOARD_SURGE} />);

    expect(screen.getByText('System under pressure')).toBeInTheDocument();
    expect(screen.getByText('All 9 services are limited, not accepting or over capacity.')).toBeInTheDocument();
  });

  it('is the warning Banner: a warning tone and a wall id', () => {
    const { container } = render(<PressureBanner board={BOARD_SURGE} />);
    const banner = container.querySelector('[data-el="WALL-PRESSURE-BANNER"]');

    expect(banner).not.toBeNull();
    expect(banner).toHaveAttribute('data-tone', 'warning');
  });

  it('shows nothing when the back end says it is not under pressure', () => {
    const { container } = render(<PressureBanner board={{ ...BOARD_A, allLimitedOrWorse: false }} />);

    expect(container).toBeEmptyDOMElement();
  });

  it('is decided by the back end flag, not by the statuses the page can see', () => {
    const allWorse = { ...BOARD_SURGE, allLimitedOrWorse: false };
    expect(render(<PressureBanner board={allWorse} />).container).toBeEmptyDOMElement();
  });

  it('does not count out-of-hours services: 3 of 9 closed leaves 6', () => {
    const entries = [...SURGE_ENTRIES.slice(0, 6), ...QUIET_ENTRIES.slice(0, 3)];
    render(<PressureBanner board={{ ...BOARD_SURGE, entries }} />);

    expect(screen.getByText('All 6 services are limited, not accepting or over capacity.')).toBeInTheDocument();
  });

  it('says so in words, not "All 1 services", when one service is in hours', () => {
    const entries = [SURGE_ENTRIES[0], ...QUIET_ENTRIES.slice(0, 3)];
    render(<PressureBanner board={{ ...BOARD_SURGE, entries }} />);

    expect(screen.getByText('The only service in hours is limited, not accepting or over capacity.')).toBeInTheDocument();
    expect(screen.queryByText(/All 1/)).toBeNull();
  });

  it('shows nothing when no service is in hours, whatever the flag says: it would claim "All 0 services"', () => {
    const entries = QUIET_ENTRIES.filter((e) => e.status === 'out-of-hours');
    const { container } = render(<PressureBanner board={{ ...BOARD_QUIET, entries, allLimitedOrWorse: true }} />);

    expect(entries.length).toBeGreaterThan(0);
    expect(container).toBeEmptyDOMElement();
  });

  it('counts a service of any in-hours status, not only the limited ones the flag speaks of', () => {
    const entries = [entry({ serviceId: 'a', name: 'A' }), entry({ serviceId: 'b', name: 'B', status: 'not-updated' })];
    render(<PressureBanner board={{ ...BOARD_SURGE, entries }} />);

    expect(screen.getByText(/^All 2 services/)).toBeInTheDocument();
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<PressureBanner board={BOARD_SURGE} />);

    expect(await runAxe(container)).toHaveNoViolations();
  });
});
