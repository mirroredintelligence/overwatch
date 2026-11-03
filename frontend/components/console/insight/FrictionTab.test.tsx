import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import type { FrictionRow } from '@/lib/console/insight';
import { FrictionTab } from './FrictionTab';

const ROWS: FrictionRow[] = [
  { elementId: 'ADV-OPT-REQUEST-BTN', kind: 'rage', route: null, events: 130, interactions: 1000, rate: 0.13, review: true },
  { elementId: 'ADV-NEEDS-POSTCODE', kind: 'validation-loop', route: null, events: 60, interactions: 500, rate: 0.12, review: true },
  { elementId: 'ADV-SEARCH-BTN', kind: 'dead', route: null, events: 20, interactions: 500, rate: 0.04, review: false },
  { elementId: 'PAGE', kind: 'u-turn', route: '/advisor/board', events: 15, interactions: null, rate: null, review: false },
];

describe('FrictionTab', () => {
  it('marks the rows the back end flagged with Review, and leaves the others unmarked', () => {
    render(<FrictionTab rows={ROWS} suppressedGroups={0} />);

    const table = screen.getByRole('table', { name: /friction by element/i });
    expect(within(table).getByRole('row', { name: /ADV-OPT-REQUEST-BTN/ })).toHaveTextContent('Review');
    expect(within(table).getByRole('row', { name: /ADV-NEEDS-POSTCODE/ })).toHaveTextContent('Review');
    expect(within(table).getByRole('row', { name: /ADV-SEARCH-BTN/ })).not.toHaveTextContent('Review');
  });

  it('does not flag a row from its rate: the back end decides, so exactly 5% is not marked', () => {
    const rows: FrictionRow[] = [
      { elementId: 'ADV-X-BTN', kind: 'dead', route: null, events: 5, interactions: 100, rate: 0.05, review: false },
    ];
    render(<FrictionTab rows={rows} suppressedGroups={0} />);

    expect(screen.getByRole('row', { name: /ADV-X-BTN/ })).not.toHaveTextContent('Review');
  });

  it('says that elements over 5% are reviewed, and shows the rate as a number', () => {
    render(<FrictionTab rows={ROWS} suppressedGroups={0} />);

    expect(screen.getByText('Elements over 5% are reviewed.')).toBeInTheDocument();
    expect(screen.getByText('13%')).toBeInTheDocument();
  });

  it('shows the route of friction on the page itself and a dash for the rate it has none of', () => {
    render(<FrictionTab rows={ROWS} suppressedGroups={0} />);

    const page = screen.getByRole('row', { name: /PAGE/ });
    expect(page).toHaveTextContent('/advisor/board');
    expect(page).toHaveTextContent('–');
  });

  it('says how many groups are left out for having fewer than 10 sessions', () => {
    const { rerender } = render(<FrictionTab rows={ROWS} suppressedGroups={0} />);
    expect(screen.queryByText(/fewer than 10 sessions/)).not.toBeInTheDocument();

    rerender(<FrictionTab rows={ROWS} suppressedGroups={1} />);
    expect(screen.getByText('1 element or page with fewer than 10 sessions is not shown.')).toBeInTheDocument();

    rerender(<FrictionTab rows={ROWS} suppressedGroups={3} />);
    expect(screen.getByText('3 elements or pages with fewer than 10 sessions are not shown.')).toBeInTheDocument();
  });

  it('offers no link to example sessions: no route serves them, so the board element is not drawn', () => {
    render(<FrictionTab rows={ROWS} suppressedGroups={0} />);

    expect(screen.queryByRole('link', { name: /show example sessions/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  it('shows the friction table without an interactions or examples column, as the board does', () => {
    render(<FrictionTab rows={ROWS} suppressedGroups={0} />);

    const table = screen.getByRole('table', { name: /friction by element/i });
    expect(within(table).getByRole('columnheader', { name: 'Rate' })).toBeInTheDocument();
    expect(within(table).queryByRole('columnheader', { name: 'Interactions' })).not.toBeInTheDocument();
    expect(within(table).queryByRole('columnheader', { name: 'Examples' })).not.toBeInTheDocument();
  });

  it('marks a flagged row with its word and a shape, the shape hidden from a screen reader', () => {
    render(<FrictionTab rows={ROWS} suppressedGroups={0} />);

    const flagged = screen.getByRole('row', { name: /ADV-OPT-REQUEST-BTN/ });
    expect(flagged).toHaveTextContent('Review');
    expect(flagged.querySelector('[aria-hidden="true"]')).not.toBeNull();
    expect(flagged).toHaveAttribute('data-flagged');
    expect(screen.getByRole('row', { name: /ADV-SEARCH-BTN/ })).not.toHaveAttribute('data-flagged');
  });

  it('passes vitest-axe', async () => {
    const { container } = render(<FrictionTab rows={ROWS} suppressedGroups={2} />);

    expect(await runAxe(container)).toHaveNoViolations();
  });
});
