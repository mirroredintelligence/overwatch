import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { WEEK_BODY, WEEK_WITHHELD_BODY } from '@/test/fixtures/network';
import { parseWeek } from '@/lib/network/parse';
import { NetworkWeek } from './NetworkWeek';

// TEN-082, the screen (docs/design/network-ui.md, NetworkWeek): only capacity-derived measures (the hours
// the board was sampled, on-time updates, the share of each status, the hours at each pressure, the pressure
// over time), small groups hidden ("Not shown: fewer than 10."), a week made from too few organisations
// withheld whole, and no breakdown by member, ever. It is a history of what the board showed, not a live
// status.

const week = parseWeek(WEEK_BODY, 'backend');
const withheld = parseWeek(WEEK_WITHHELD_BODY, 'backend');

function show(data = week) {
  return render(<NetworkWeek week={data} networkName="Sample Network" />);
}

describe('NetworkWeek', () => {
  it('has the network’s name, the days of the week and what the screen is', () => {
    show();
    expect(screen.getByRole('heading', { level: 1, name: 'Sample Network this week' })).toBeInTheDocument();
    expect(screen.getByText('19 to 25 Oct')).toBeInTheDocument();
    expect(screen.getByText('This is what the network board showed, hour by hour. It is not a live status.')).toBeInTheDocument();
  });

  it('shows the hours sampled and the capacity updates on time', () => {
    show();
    expect(screen.getByText('134 hours sampled')).toBeInTheDocument();
    expect(screen.getByText('75% capacity updates on time')).toBeInTheDocument();
  });

  it('shows the share of each status, a hidden one as "Not shown: fewer than 10."', () => {
    show();
    const shares = screen.getByRole('list', { name: 'Share of services by status' });
    expect(within(shares).getByText('Accepting 48%')).toBeInTheDocument();
    expect(within(shares).getByText('Not updated 22%')).toBeInTheDocument();
    const over = within(shares).getByText(/Over capacity/);
    expect(over.parentElement).toHaveTextContent('Not shown: fewer than 10.');
    expect(within(shares).queryByText(/Over capacity \d/)).toBeNull();
  });

  it('shows the hours at each pressure, a hidden one not shown', () => {
    show();
    const hours = screen.getByRole('list', { name: 'Hours at each pressure' });
    expect(within(hours).getByText('Normal 100 hours')).toBeInTheDocument();
    expect(within(hours).getByText('Watch 30 hours')).toBeInTheDocument();
    expect(within(hours).getByText(/High/).parentElement).toHaveTextContent('Not shown: fewer than 10.');
  });

  it('lists the pressure over time, hour by hour, in London time, in a disclosure', () => {
    show();
    const details = screen.getByText('Pressure over time (2 hours)').closest('details')!;
    expect(details).toBeInTheDocument();
    const rows = within(details).getAllByRole('row').slice(1);
    expect(rows).toHaveLength(2);
    expect(within(rows[0]!).getByText('Normal')).toBeInTheDocument();
    expect(within(rows[1]!).getByText('Watch')).toBeInTheDocument();
  });

  it('says that no breakdown by member is shown', () => {
    show();
    expect(screen.getByText('No per-member breakdown is shown.')).toBeInTheDocument();
  });

  it('withholds a week made from too few organisations, whole: no figure, no series', () => {
    const { container } = show(withheld);
    expect(screen.getByText('This week is not shown. Too few organisations shared capacity for it to be shown without identifying one.')).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/\d+% |\d+ hours/);
    expect(screen.queryByText(/Pressure over time/)).toBeNull();
    expect(screen.getByText('No per-member breakdown is shown.')).toBeInTheDocument();
  });

  it('names no organisation, service or id', () => {
    const { container } = show();
    expect(container.innerHTML).not.toMatch(/Sample Area|UCR|trust-|tenant|net-sample|grant/i);
  });

  it('has no axe violations, withheld or not', async () => {
    const a = show();
    expect((await runAxe(a.container)).violations).toEqual([]);
    a.unmount();
    const b = show(withheld);
    expect((await runAxe(b.container)).violations).toEqual([]);
  });
});
