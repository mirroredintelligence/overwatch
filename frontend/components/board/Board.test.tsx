import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { BOARD_A, BOARD_QUIET, BOARD_SURGE, MAIN_ENTRIES, QUIET_ENTRIES, SURGE_ENTRIES } from '@/test/fixtures/board';
import { Board } from './Board';

function tiles(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>('[data-el="WALL-TILE"]'));
}

describe('Board header', () => {
  it('shows the organisation heading, the line, the London time and the date', () => {
    render(<Board board={BOARD_A} />);

    expect(screen.getByRole('heading', { level: 1, name: 'Dorset urgent care capacity' })).toBeInTheDocument();
    expect(screen.getByText('Single point of access')).toBeInTheDocument();
    expect(screen.getByText('14:12')).toBeInTheDocument();
    expect(screen.getByText('Friday 23 October')).toBeInTheDocument();
  });

  it('takes the organisation name from the board it was given, never from a constant', () => {
    render(<Board board={{ ...BOARD_A, organisation: 'Another area' }} />);

    expect(screen.getByRole('heading', { level: 1, name: 'Another area urgent care capacity' })).toBeInTheDocument();
    expect(screen.queryByText(/Dorset/)).toBeNull();
  });

  it('has a plain heading when the back end sends no organisation name', () => {
    render(<Board board={{ ...BOARD_A, organisation: null }} />);

    expect(screen.getByRole('heading', { level: 1, name: 'Urgent care capacity' })).toBeInTheDocument();
  });

  it('marks the time as a machine-readable instant', () => {
    const { container } = render(<Board board={BOARD_A} />);

    expect(container.querySelector('time')).toHaveAttribute('datetime', '2026-10-23T13:12:00Z');
  });
});

describe('Board body', () => {
  it('shows one tile for each service, in the order the back end sent them', () => {
    const { container } = render(<Board board={BOARD_A} />);

    expect(tiles(container).map((t) => t.getAttribute('data-service-id'))).toEqual(
      MAIN_ENTRIES.map((e) => e.serviceId),
    );
  });

  it('does not re-sort: a reversed board stays reversed', () => {
    const reversed = { ...BOARD_A, entries: [...MAIN_ENTRIES].reverse() };
    const { container } = render(<Board board={reversed} />);

    expect(tiles(container).map((t) => t.getAttribute('data-service-id'))).toEqual(
      reversed.entries.map((e) => e.serviceId),
    );
  });

  it('puts the tiles in a list', () => {
    render(<Board board={BOARD_A} />);

    expect(within(screen.getByRole('list', { name: 'Services' })).getAllByRole('listitem')).toHaveLength(9);
  });

  it('renders the legend and the footer text', () => {
    render(<Board board={BOARD_A} />);
    const legend = within(screen.getByRole('list', { name: 'Status key' }));

    expect(legend.getByText('Accepting')).toBeInTheDocument();
    expect(legend.getByText('Limited: phone to confirm')).toBeInTheDocument();
    expect(legend.getByText('Not accepting')).toBeInTheDocument();
    expect(legend.getByText('Over capacity')).toBeInTheDocument();
    expect(legend.getByText('Not updated: treat as unknown, phone')).toBeInTheDocument();
    expect(screen.getByText('No patient information on this screen')).toBeInTheDocument();
  });

  it('measures every age from the back end clock, not from the browser clock', () => {
    const later = { ...BOARD_A, generatedAt: '2026-10-23T13:22:00Z' };
    render(<Board board={later} />);

    expect(screen.getByText('Updated 19 min ago · next due 14:30')).toBeInTheDocument();
    expect(screen.getByText('14:22')).toBeInTheDocument();
  });

  it('says so, and tells people what to do, when the board lists no services', () => {
    render(<Board board={{ ...BOARD_A, entries: [] }} />);

    expect(screen.getByRole('status')).toHaveTextContent(
      'No services are listed. Use the whiteboard and phone process.',
    );
  });
});

describe('Board privacy and accessibility', () => {
  it('shows no back-end id except data-service-id, and nothing shaped like a postcode or an NHS number', () => {
    const { container } = render(<Board board={BOARD_A} />);
    const html = container.innerHTML.replace(/data-service-id="[^"]*"/g, '');

    expect(tiles(container)).toHaveLength(9);
    for (const e of MAIN_ENTRIES) expect(html).not.toContain(e.serviceId);
    expect(container.textContent).not.toMatch(/\b[A-Z]{1,2}\d[A-Z\d]? ?\d[A-Z]{2}\b/);
    expect(container.textContent).not.toMatch(/\b\d{3} ?\d{3} ?\d{4}\b/);
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<Board board={BOARD_A} />);

    expect(tiles(container)).toHaveLength(9);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});

describe('Board: last known (W06)', () => {
  const lastKnown = {
    mode: 'last-known' as const,
    reason: 'offline' as const,
    since: '2026-10-23T13:02:00Z',
    asOf: '2026-10-23T13:02:00Z',
    now: '2026-10-23T13:30:00Z',
    ageMs: 1_680_000,
  };

  it('shows the banner and turns every tile into a Last known tile, keeping the order and the numbers', () => {
    const { container } = render(<Board board={BOARD_A} lastKnown={lastKnown} />);

    expect(screen.getByRole('alert')).toHaveTextContent('Tool offline since 14:02');
    expect(tiles(container)).toHaveLength(BOARD_A.entries.length);
    expect(tiles(container).map((t) => t.getAttribute('data-service-id'))).toEqual(MAIN_ENTRIES.map((e) => e.serviceId));
    for (const t of tiles(container)) {
      expect(t).toHaveAttribute('data-status', 'last-known');
      expect(within(t).getByText('Do not rely on this. Phone to confirm.')).toBeInTheDocument();
    }
    expect(within(tiles(container)[0]).getByText('4')).toBeInTheDocument();
  });

  it('leaves the header time at the time the board was built, not the time now', () => {
    render(<Board board={BOARD_A} lastKnown={lastKnown} />);

    expect(screen.getByText('14:12')).toBeInTheDocument();
    expect(screen.queryByText('14:30')).toBeNull();
  });

  it('ages the figures from the time now, not from the time the board was built', () => {
    const { container } = render(<Board board={BOARD_A} lastKnown={lastKnown} />);

    // The first tile reported at 14:03 London; now is 14:30 London.
    expect(tiles(container)[0].textContent).toContain('Last known 14:03');
    expect(tiles(container)[0].textContent).toContain('27 min ago');
  });

  it('has no banner and no Last known word when the board is current', () => {
    const { container } = render(<Board board={BOARD_A} />);

    expect(screen.queryByRole('alert')).toBeNull();
    expect(container.textContent).not.toContain('Last known');
    expect(container.textContent).not.toContain('Live updates paused');
  });

  it('says in words that live updates are paused when the stream is down but the board is still refreshing', () => {
    const { container } = render(<Board board={BOARD_A} streamPaused />);

    expect(container.querySelector('[data-el="WALL-STREAM-NOTE"]')).toHaveTextContent(
      'Live updates paused. This board refreshes every minute.',
    );
    expect(screen.queryByRole('alert')).toBeNull();
    for (const t of tiles(container)) expect(t).not.toHaveAttribute('data-status', 'last-known');
  });

  it('does not add a second announcement: the stream note has no live role, and only the banner is an alert', () => {
    const { container } = render(<Board board={BOARD_A} streamPaused />);
    expect(container.querySelector('[aria-live], [role="alert"], [role="status"]')).toBeNull();

    const down = render(<Board board={BOARD_A} lastKnown={lastKnown} streamPaused />);
    expect(down.container.querySelectorAll('[role="alert"]')).toHaveLength(1);
    expect(down.container.querySelector('[data-el="WALL-STREAM-NOTE"]')).toBeNull();
  });

  it('has no axe violations while last known', async () => {
    const { container } = render(<Board board={BOARD_A} lastKnown={lastKnown} />);

    expect(tiles(container)).toHaveLength(BOARD_A.entries.length);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('shows the banner and no tiles for an empty board that is last known', () => {
    const { container } = render(<Board board={{ ...BOARD_A, entries: [] }} lastKnown={lastKnown} />);

    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(tiles(container)).toHaveLength(0);
  });
});

describe('Board: the system under pressure banner (W07)', () => {
  const BANNER = 'All 9 services are limited, not accepting or over capacity.';
  const lastKnown = {
    mode: 'last-known' as const,
    reason: 'offline' as const,
    since: '2026-10-23T13:02:00Z',
    asOf: '2026-10-23T13:02:00Z',
    now: '2026-10-23T13:30:00Z',
    ageMs: 1_680_000,
  };

  it('shows "System under pressure" and the count above the grid when allLimitedOrWorse is true (BoardSurge)', () => {
    const { container } = render(<Board board={BOARD_SURGE} />);
    const banner = container.querySelector('[data-el="WALL-PRESSURE-BANNER"]');
    const grid = screen.getByRole('list', { name: 'Services' });

    expect(banner).toHaveTextContent('System under pressure');
    expect(screen.getByText(BANNER)).toBeInTheDocument();
    expect(tiles(container)).toHaveLength(9);
    // Above the grid in reading order.
    expect(banner?.compareDocumentPosition(grid)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  it('shows no banner when allLimitedOrWorse is false', () => {
    const { container } = render(<Board board={BOARD_A} />);

    expect(container.querySelector('[data-el="WALL-PRESSURE-BANNER"]')).toBeNull();
    expect(container.textContent).not.toContain('System under pressure');
  });

  it('is decided by the flag: every tile limited or worse with the flag false shows no banner', () => {
    const { container } = render(<Board board={{ ...BOARD_SURGE, allLimitedOrWorse: false }} />);

    expect(container.querySelector('[data-el="WALL-PRESSURE-BANNER"]')).toBeNull();
  });

  it('does not count out-of-hours services in the number', () => {
    const entries = [...SURGE_ENTRIES.slice(0, 6), ...QUIET_ENTRIES.slice(0, 3)];
    const { container } = render(<Board board={{ ...BOARD_SURGE, entries }} />);

    expect(tiles(container)).toHaveLength(9);
    expect(screen.getByText('All 6 services are limited, not accepting or over capacity.')).toBeInTheDocument();
    expect(screen.queryByText(BANNER)).toBeNull();
  });

  it('shows none on the quiet board, where most services are out of hours', () => {
    const { container } = render(<Board board={BOARD_QUIET} />);

    expect(container.querySelector('[data-el="WALL-PRESSURE-BANNER"]')).toBeNull();
  });

  it('is never shown as current while the board is last known: the Last known banner is the only banner', () => {
    const { container } = render(<Board board={BOARD_SURGE} lastKnown={lastKnown} />);

    expect(container.querySelector('[data-el="WALL-PRESSURE-BANNER"]')).toBeNull();
    expect(container.textContent).not.toContain('System under pressure');
    expect(container.querySelectorAll('[role="alert"]')).toHaveLength(1);
    expect(screen.getByRole('alert')).toHaveTextContent('Tool offline since 14:02');
    for (const t of tiles(container)) expect(t).toHaveAttribute('data-status', 'last-known');
  });

  it('is shown beside the quiet "live updates paused" note, not instead of it', () => {
    const { container } = render(<Board board={BOARD_SURGE} streamPaused />);

    expect(container.querySelector('[data-el="WALL-STREAM-NOTE"]')).toBeInTheDocument();
    expect(container.querySelector('[data-el="WALL-PRESSURE-BANNER"]')).toBeInTheDocument();
  });

  it('has no axe violations on the surge board', async () => {
    const { container } = render(<Board board={BOARD_SURGE} />);

    expect(tiles(container)).toHaveLength(9);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});

describe('Board: the variant tiles together (W07)', () => {
  it('the surge board shows its over-capacity, not-accepting and limited tiles by word, with the pending counts', () => {
    const { container } = render(<Board board={BOARD_SURGE} />);
    const byId = (id: string) => container.querySelector<HTMLElement>(`[data-service-id="${id}"]`) as HTMLElement;

    expect(within(byId('svc-hospital-at-home')).getByText('Over capacity')).toBeInTheDocument();
    expect(within(byId('svc-hospital-at-home')).getByText('+4')).toBeInTheDocument();
    expect(within(byId('svc-hospital-at-home')).getByText('Used 16 of 12 · 1 pending')).toBeInTheDocument();
    expect(within(byId('svc-virtual-ward')).getByText('+1')).toBeInTheDocument();
    expect(within(byId('svc-ucr-west')).getByText('Limited')).toBeInTheDocument();
    expect(within(byId('svc-ucr-west')).getByText('Used 7 of 8 · 1 pending')).toBeInTheDocument();
    expect(within(byId('svc-ucr-east')).getByText('Not accepting')).toBeInTheDocument();
    expect(container.querySelectorAll('[data-el="WALL-TILE-PENDING"]')).toHaveLength(2);
  });

  it('the quiet board (02:40) shows six out-of-hours tiles reopening at 08:00 beside three open ones', () => {
    const { container } = render(<Board board={BOARD_QUIET} />);
    const closed = tiles(container).filter((t) => t.getAttribute('data-status') === 'out-of-hours');

    expect(screen.getByText('02:40')).toBeInTheDocument();
    expect(screen.getByText('Saturday 24 October')).toBeInTheDocument();
    expect(closed).toHaveLength(6);
    for (const t of closed) {
      expect(within(t).getByText('Reopens 08:00')).toBeInTheDocument();
      expect(within(t).getByText('Closed overnight')).toBeInTheDocument();
    }
    expect(tiles(container)).toHaveLength(9);
    expect(within(tiles(container)[4]).getByText('Updated 1 hr 20 min ago · next due 06:00')).toBeInTheDocument();
  });

  it('has no axe violations on the quiet board', async () => {
    const { container } = render(<Board board={BOARD_QUIET} />);

    expect(tiles(container)).toHaveLength(9);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('shows no back-end id, tenant or organisation other than its own heading, on any variant board', () => {
    for (const board of [BOARD_SURGE, BOARD_QUIET]) {
      const { container, unmount } = render(<Board board={board} />);
      const html = container.innerHTML.replace(/data-service-id="[^"]*"/g, '');

      for (const e of board.entries) expect(html).not.toContain(e.serviceId);
      expect(container.textContent).not.toContain('Neighbouring');
      unmount();
    }
  });
});
