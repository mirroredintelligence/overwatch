import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { WEEK_BODY, WEEK_WITHHELD_BODY } from '@/test/fixtures/network';
import { parseWeek } from '@/lib/network/parse';
import { NetworkWeek } from './NetworkWeek';

// TEN-082, the screen (docs/design/network-ui.md, NetworkWeek; redesign board NWeek): only capacity-derived
// measures (the hours the board was sampled, on-time updates, the share of each status, the hours at each
// pressure, the pressure over time as a 7 by 24 grid with a table behind it), small groups hidden ("Not shown:
// fewer than 10."), a week made from too few organisations withheld whole in its own card, and no breakdown by
// member, ever. It is a history of what the board showed, not a live status.

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

  it('shows the hours sampled and the capacity updates on time as two figure cards', () => {
    show();
    const figures = within(screen.getByRole('list', { name: 'Figures for the week' })).getAllByRole('listitem');
    expect(figures).toHaveLength(2);
    expect(within(figures[0]!).getByText('134')).toBeInTheDocument();
    expect(within(figures[0]!).getByText('hours sampled')).toBeInTheDocument();
    expect(within(figures[1]!).getByText('75%')).toBeInTheDocument();
    expect(within(figures[1]!).getByText('capacity updates on time')).toBeInTheDocument();
    // A screen reader hears each as one phrase.
    expect(screen.getByText('134 hours sampled')).toBeInTheDocument();
    expect(screen.getByText('75% capacity updates on time')).toBeInTheDocument();
  });

  it('draws the share of each status as one stacked bar whose name has every share, a hidden one as not shown', () => {
    show();
    const bar = screen.getByRole('img', { name: /^Accepting 48%, Limited 20%, Not accepting 5%, Over capacity not shown, Not updated 22%/ });
    // One segment for each status that has a share; the hidden one is not drawn.
    expect(bar.querySelectorAll('[data-status]')).toHaveLength(4);
    expect(bar.querySelector('[data-status="over-capacity"]')).toBeNull();
  });

  it('lists the share of each status beside the bar, a hidden one as "Not shown: fewer than 10."', () => {
    show();
    const shares = screen.getByRole('list', { name: 'Share of services by status' });
    expect(within(shares).getByText('Accepting 48%')).toBeInTheDocument();
    expect(within(shares).getByText('Not updated 22%')).toBeInTheDocument();
    const over = within(shares).getByText(/Over capacity/);
    expect(over.parentElement).toHaveTextContent('Not shown: fewer than 10.');
    expect(within(shares).queryByText(/Over capacity \d/)).toBeNull();
  });

  it('says the out-of-hours share on its own line, not in the bar', () => {
    show();
    expect(screen.getByText('Out of hours: 5%')).toBeInTheDocument();
  });

  it('shows the hours at each pressure as three boxes, a hidden one not shown', () => {
    show();
    const hours = screen.getByRole('list', { name: 'Hours at each pressure' });
    const boxes = within(hours).getAllByRole('listitem');
    expect(boxes).toHaveLength(3);
    expect(within(boxes[0]!).getByText('100 hours')).toBeInTheDocument();
    expect(within(boxes[0]!).getByText('Normal')).toBeInTheDocument();
    expect(within(boxes[1]!).getByText('30 hours')).toBeInTheDocument();
    expect(within(boxes[1]!).getByText('Watch')).toBeInTheDocument();
    expect(boxes[2]).toHaveTextContent('High');
    expect(boxes[2]).toHaveTextContent('Not shown: fewer than 10.');
    expect(within(boxes[2]!).queryByText(/\d hours?/)).toBeNull();
  });

  it('draws the pressure over time as a 7 by 24 grid, one cell for each hour of each day, in London time', () => {
    const { container } = show();
    const grid = screen.getByRole('img', { name: /^Pressure for each hour of the week, by day and hour/ });
    expect(grid.querySelectorAll('[data-pressure]')).toHaveLength(168);
    // 00:00 and 01:00 UTC on Monday 19 Oct are 01:00 and 02:00 in London (summer time).
    expect(grid.querySelector('[data-day="0"][data-hour="1"]')).toHaveAttribute('data-pressure', 'normal');
    expect(grid.querySelector('[data-day="0"][data-hour="2"]')).toHaveAttribute('data-pressure', 'watch');
    expect(grid.querySelector('[data-day="0"][data-hour="3"]')).toHaveAttribute('data-pressure', 'none');
    expect(grid.querySelectorAll('[data-pressure="normal"], [data-pressure="watch"], [data-pressure="high"]')).toHaveLength(2);
    for (const day of ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']) expect(container).toHaveTextContent(day);
  });

  it('names each pressure in a legend, with the hours that were not sampled', () => {
    show();
    const legend = screen.getByRole('list', { name: 'Pressure key' });
    for (const word of ['Normal', 'Watch', 'High', 'Not sampled']) expect(within(legend).getByText(word)).toBeInTheDocument();
    expect(screen.getByText('The highest pressure of each hour the board was sampled. Each hour is also in the table.')).toBeInTheDocument();
  });

  it('lists the pressure over time, hour by hour, in London time, in a table behind "Show as a table"', () => {
    show();
    const details = screen.getByText('Show as a table').closest('details')!;
    expect(details).toBeInTheDocument();
    const rows = within(details).getAllByRole('row').slice(1);
    expect(rows).toHaveLength(2);
    expect(within(rows[0]!).getByText('Normal')).toBeInTheDocument();
    expect(within(rows[1]!).getByText('Watch')).toBeInTheDocument();
  });

  it('says that only capacity-derived measures are shown and no breakdown by member', () => {
    show();
    expect(screen.getByText('Capacity-derived measures only. There is no breakdown by member. Not shown: fewer than 10.')).toBeInTheDocument();
  });

  it('withholds a week made from too few organisations, whole, in its own card: no figure, no series', () => {
    const { container } = show(withheld);
    expect(screen.getByRole('heading', { name: 'If too few organisations shared' })).toBeInTheDocument();
    expect(screen.getByText('This week is not shown. Too few organisations shared capacity for it to be shown without identifying one.')).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/\d+% |\d+ hours/);
    expect(screen.queryByRole('img')).toBeNull();
    expect(screen.queryByText('Show as a table')).toBeNull();
    expect(screen.queryByRole('list', { name: 'Figures for the week' })).toBeNull();
    expect(screen.getByText('Capacity-derived measures only. There is no breakdown by member. Not shown: fewer than 10.')).toBeInTheDocument();
  });

  it('does not show the withheld card for a week that is shown', () => {
    show();
    expect(screen.queryByText(/Too few organisations shared/)).toBeNull();
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
