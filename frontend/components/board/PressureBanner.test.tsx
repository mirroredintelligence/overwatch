import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { BOARD_A, BOARD_QUIET, BOARD_SURGE, entry, QUIET_ENTRIES, SURGE_ENTRIES } from '@/test/fixtures/board';
import { PressureBanner, QuietBanner } from './PressureBanner';

describe('QuietBanner', () => {
  const OUT = QUIET_ENTRIES.filter((e) => e.status === 'out-of-hours');
  const OPEN = QUIET_ENTRIES.filter((e) => e.status !== 'out-of-hours');

  it('says how many services are out of hours until when, and that they are not counted, and how many take referrals', () => {
    const { container } = render(<QuietBanner board={BOARD_QUIET} />);
    const banner = container.querySelector('[data-el="WALL-QUIET-BANNER"]');

    expect(banner).toHaveTextContent('Quiet overnight');
    expect(banner).toHaveTextContent('6 of 9 services are out of hours until 08:00, so they are not counted. 3 take referrals now.');
    expect(screen.getByRole('status')).toBe(banner);
    expect(banner?.querySelector('[aria-hidden="true"]')).not.toBeNull();
  });

  it('shows nothing when most services are in hours, or when there are none', () => {
    expect(render(<QuietBanner board={BOARD_A} />).container).toBeEmptyDOMElement();
    expect(render(<QuietBanner board={{ ...BOARD_QUIET, entries: [] }} />).container).toBeEmptyDOMElement();
    const half = { ...BOARD_QUIET, entries: [...OUT.slice(0, 3), ...OPEN.slice(0, 3)] };
    expect(render(<QuietBanner board={half} />).container).toBeEmptyDOMElement();
  });

  it('does not say overnight in the daytime: it says the services are out of hours', () => {
    render(<QuietBanner board={{ ...BOARD_QUIET, generatedAt: '2026-10-24T11:00:00Z' }} />);

    expect(screen.getByRole('status')).toHaveTextContent('Quiet: most services are out of hours');
    expect(screen.getByRole('status')).not.toHaveTextContent('overnight');
  });

  it('names no reopening time when the services do not share one, or one of them has none', () => {
    const differing = OUT.map((e, i) => (i === 0 ? { ...e, nextDueAt: '2026-10-24T09:00:00Z' } : e));
    const { unmount } = render(<QuietBanner board={{ ...BOARD_QUIET, entries: [...differing, ...OPEN] }} />);
    expect(screen.getByRole('status')).toHaveTextContent('6 of 9 services are out of hours, so they are not counted.');
    expect(screen.getByRole('status')).not.toHaveTextContent('until');
    unmount();

    const missing = OUT.map((e, i) => (i === 0 ? { ...e, nextDueAt: null } : e));
    render(<QuietBanner board={{ ...BOARD_QUIET, entries: [...missing, ...OPEN] }} />);
    expect(screen.getByRole('status')).not.toHaveTextContent('until');
  });

  it('says so in words when none, or one, is in hours, and says tomorrow for a reopening on another day', () => {
    const { unmount } = render(<QuietBanner board={{ ...BOARD_QUIET, entries: OUT }} />);
    expect(screen.getByRole('status')).toHaveTextContent('All 6 services are out of hours until 08:00, so they are not counted. None take referrals now.');
    unmount();

    const { unmount: second } = render(<QuietBanner board={{ ...BOARD_QUIET, entries: [...OUT, OPEN[0]] }} />);
    expect(screen.getByRole('status')).toHaveTextContent('6 of 7 services are out of hours until 08:00, so they are not counted. 1 takes referrals now.');
    second();

    const late = { ...BOARD_QUIET, generatedAt: '2026-10-23T22:30:00Z' };
    render(<QuietBanner board={late} />);
    expect(screen.getByRole('status')).toHaveTextContent('until 08:00 tomorrow');
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<QuietBanner board={BOARD_QUIET} />);

    expect(await runAxe(container)).toHaveNoViolations();
  });
});

describe('PressureBanner', () => {
  it('shows "System under pressure" and the count of services when every service in hours is limited or worse', () => {
    render(<PressureBanner board={BOARD_SURGE} />);

    expect(screen.getByText('System under pressure')).toBeInTheDocument();
    expect(screen.getByText('All 9 services are limited, not accepting or over capacity.')).toBeInTheDocument();
  });

  it('is a warning with a wall id, said politely (a status, not an alert), with a shape that is not read out', () => {
    const { container } = render(<PressureBanner board={BOARD_SURGE} />);
    const banner = container.querySelector('[data-el="WALL-PRESSURE-BANNER"]');

    expect(banner).not.toBeNull();
    expect(banner).toHaveAttribute('data-tone', 'warning');
    expect(screen.getByRole('status')).toBe(banner);
    expect(screen.queryByRole('alert')).toBeNull();
    expect(banner?.querySelector('[aria-hidden="true"]')).not.toBeNull();
  });

  it('says what to do: phone to confirm before offering a service', () => {
    render(<PressureBanner board={BOARD_SURGE} />);

    expect(screen.getByRole('status')).toHaveTextContent('Phone to confirm before you offer a service.');
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
