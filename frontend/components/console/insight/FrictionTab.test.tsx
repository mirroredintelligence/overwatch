import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { FrictionTab } from './FrictionTab';

const ROWS = [
  { elementId: 'ADV-OPT-REQUEST-BTN', kind: 'rage', events: 130, interactions: 1000, rate: 0.13 },
  { elementId: 'ADV-NEEDS-POSTCODE', kind: 'validation-loop', events: 60, interactions: 500, rate: 0.12 },
  { elementId: 'ADV-SEARCH-BTN', kind: 'dead', events: 20, interactions: 500, rate: 0.04 },
];

describe('FrictionTab', () => {
  it('marks the rows at 13% and 12% with Review, and leaves the 4% row unmarked', () => {
    render(<FrictionTab rows={ROWS} />);

    const table = screen.getByRole('table', { name: /friction by element/i });
    const hot = within(table).getByRole('row', { name: /ADV-OPT-REQUEST-BTN/ });
    const warm = within(table).getByRole('row', { name: /ADV-NEEDS-POSTCODE/ });
    const cool = within(table).getByRole('row', { name: /ADV-SEARCH-BTN/ });
    expect(hot).toHaveTextContent('Review');
    expect(warm).toHaveTextContent('Review');
    expect(cool).not.toHaveTextContent('Review');
  });

  it('says that elements over 5% are reviewed, and shows the rate as a number', () => {
    render(<FrictionTab rows={ROWS} />);

    expect(screen.getByText('Elements over 5% are reviewed.')).toBeInTheDocument();
    expect(screen.getByText('13%')).toBeInTheDocument();
  });

  it('links each row to the sessions for that element', () => {
    render(<FrictionTab rows={ROWS} />);

    const link = screen.getAllByRole('link', { name: /show example sessions/i })[0];
    expect(link).toHaveAttribute('href', '/console?element=ADV-OPT-REQUEST-BTN');
  });

  it('passes vitest-axe', async () => {
    const { container } = render(<FrictionTab rows={ROWS} />);

    expect(await runAxe(container)).toHaveNoViolations();
  });
});
