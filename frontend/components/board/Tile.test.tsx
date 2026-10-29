import { render, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { entry, MAIN_ENTRIES, NOW, UCR_WEST, VIRTUAL_WARD } from '@/test/fixtures/board';
import { Tile } from './Tile';

function tile(container: HTMLElement): HTMLElement {
  const found = container.querySelector<HTMLElement>('[data-el="WALL-TILE"]');
  if (!found) throw new Error('no tile was rendered');
  return found;
}

describe('Tile: accepting', () => {
  it('shows the name, category, number, unit, comment, bar label and age line', () => {
    const { container } = render(<Tile entry={UCR_WEST} now={NOW} />);
    const t = within(tile(container));

    expect(t.getByRole('heading', { name: 'UCR West' })).toBeInTheDocument();
    expect(t.getByText('Urgent community response')).toBeInTheDocument();
    expect(t.getByText('4')).toBeInTheDocument();
    expect(t.getByText('referrals in the next 2 hrs')).toBeInTheDocument();
    expect(t.getByText('Response time about 1 hr 20')).toBeInTheDocument();
    expect(t.getByText('Used 4 of 8')).toBeInTheDocument();
    expect(t.getByText('Updated 9 min ago · next due 14:30')).toBeInTheDocument();
  });

  it('has the status word Accepting, the wall tile id and the service id as data attributes', () => {
    const { container } = render(<Tile entry={UCR_WEST} now={NOW} />);
    const el = tile(container);

    expect(el).toHaveAttribute('data-service-id', 'svc-ucr-west');
    expect(el).toHaveAttribute('data-status', 'accepting');
    expect(within(el).getByText('Accepting')).toBeInTheDocument();
  });

  it('fills the bar by used over established', () => {
    const { container } = render(<Tile entry={UCR_WEST} now={NOW} />);
    const fill = container.querySelector<HTMLElement>('[data-bar-fill]');

    expect(fill?.style.width).toBe('50%');
  });

  it('leaves out the comment line when there is no comment', () => {
    const { container } = render(<Tile entry={{ ...UCR_WEST, comment: null }} now={NOW} />);

    expect(within(tile(container)).getByText('UCR West')).toBeInTheDocument();
    expect(within(tile(container)).queryByText('Response time about 1 hr 20')).toBeNull();
    expect(container.querySelector('[data-el="WALL-TILE-COMMENT"]')).toBeNull();
  });

  it('shows 0 for no free places, not a blank or a question mark', () => {
    const { container } = render(
      <Tile
        entry={entry({
          serviceId: 'svc-closed',
          name: 'SDEC · Site 2',
          status: 'not-accepting',
          effectiveAvailable: 0,
          used: 8,
          unitLabel: 'slots left today',
        })}
        now={NOW}
      />,
    );
    const t = within(tile(container));

    expect(t.getByText('Not accepting')).toBeInTheDocument();
    expect(t.getByText('0')).toBeInTheDocument();
    expect(t.getByText('Used 8 of 8')).toBeInTheDocument();
    expect(container.querySelector<HTMLElement>('[data-bar-fill]')?.style.width).toBe('100%');
  });

  it('works out the free number from established minus used when the service reports occupancy', () => {
    const { container } = render(
      <Tile
        entry={entry({
          serviceId: 'svc-occ',
          name: 'Occupancy ward',
          effectiveAvailable: null,
          used: 7,
          established: 12,
          unitLabel: 'beds free',
        })}
        now={NOW}
      />,
    );

    expect(within(tile(container)).getByText('5')).toBeInTheDocument();
  });

  it('shows ? and Phone to confirm, never a number, when there is no figure to show', () => {
    const { container } = render(
      <Tile entry={entry({ serviceId: 'svc-none', name: 'No figure', effectiveAvailable: null, used: null })} now={NOW} />,
    );
    const t = within(tile(container));

    expect(t.getByText('?')).toBeInTheDocument();
    expect(t.getByText('Phone to confirm')).toBeInTheDocument();
    expect(t.getByText('Used ? of 8')).toBeInTheDocument();
  });
});

describe('Tile: limited', () => {
  const limited = entry({
    serviceId: 'svc-ucr-east',
    name: 'UCR East',
    status: 'limited',
    effectiveAvailable: 1,
    used: 7,
    unitLabel: 'referral in the next 2 hrs',
  });

  it('has the word Limited, not colour alone', () => {
    const { container } = render(<Tile entry={limited} now={NOW} />);
    const el = tile(container);

    expect(within(el).getByText('Limited')).toBeInTheDocument();
    expect(el).toHaveAttribute('data-status', 'limited');
    expect(el.querySelector('[data-shape="triangle"]')).not.toBeNull();
  });

  it('fills the bar by used over established exactly: 7 of 8 is 87.5%', () => {
    const { container } = render(<Tile entry={limited} now={NOW} />);

    expect(container.querySelector<HTMLElement>('[data-bar-fill]')?.style.width).toBe('87.5%');
  });
});

describe('Tile: not updated', () => {
  it('shows ?, Phone to confirm, Used ? of 10 and the age line with the was-due time', () => {
    const { container } = render(<Tile entry={VIRTUAL_WARD} now={NOW} />);
    const t = within(tile(container));

    expect(t.getByText('?')).toBeInTheDocument();
    expect(t.getByText('Phone to confirm')).toBeInTheDocument();
    expect(t.getByText('Used ? of 10')).toBeInTheDocument();
    expect(t.getByText('Not updated for 4 hrs 10 min · was due 12:00')).toBeInTheDocument();
  });

  it('has the badge word Not updated', () => {
    const { container } = render(<Tile entry={VIRTUAL_WARD} now={NOW} />);
    const badge = tile(container).querySelector('[data-status="not-updated"][data-shape]');

    expect(badge).toHaveTextContent('Not updated');
    expect(tile(container)).toHaveAttribute('data-status', 'not-updated');
  });

  it('does not show the last figure as if it were current', () => {
    const { container } = render(<Tile entry={VIRTUAL_WARD} now={NOW} />);

    // The last reported 3 beds free, and used 7 of 10: neither may be shown as a number.
    expect(within(tile(container)).getByText('?')).toBeInTheDocument();
    expect(within(tile(container)).queryByText('3')).toBeNull();
    expect(within(tile(container)).queryByText('Used 7 of 10')).toBeNull();
  });

  it('shows the age line in bold', () => {
    const { container } = render(<Tile entry={VIRTUAL_WARD} now={NOW} />);
    const line = within(tile(container)).getByText('Not updated for 4 hrs 10 min · was due 12:00');

    expect(line.closest('strong')).not.toBeNull();
  });

  it('shows the figure of a service that is not updated as unknown even when the back end sends none', () => {
    const { container } = render(
      <Tile entry={{ ...VIRTUAL_WARD, effectiveAvailable: null, used: null, reportedAt: null }} now={NOW} />,
    );

    expect(within(tile(container)).getByText('?')).toBeInTheDocument();
    expect(within(tile(container)).getByText('No figure reported yet · was due 12:00')).toBeInTheDocument();
  });
});

describe('Tile: statuses outside this task still show the word and no misleading figure', () => {
  it('over capacity shows the word Over capacity, +N and the bar full', () => {
    const over = MAIN_ENTRIES.find((e) => e.status === 'over-capacity');
    if (!over) throw new Error('fixture has no over-capacity service');
    const { container } = render(<Tile entry={over} now={NOW} />);
    const t = within(tile(container));

    expect(t.getByText('Over capacity')).toBeInTheDocument();
    expect(t.getByText('+2')).toBeInTheDocument();
    expect(t.getByText('over established capacity')).toBeInTheDocument();
    expect(t.getByText('Used 14 of 12')).toBeInTheDocument();
    expect(container.querySelector<HTMLElement>('[data-bar-fill]')?.style.width).toBe('100%');
  });

  it('out of hours shows the word Out of hours and no number', () => {
    const { container } = render(
      <Tile
        entry={entry({
          serviceId: 'svc-ooh',
          name: 'Evening service',
          status: 'out-of-hours',
          effectiveAvailable: 4,
          used: 4,
        })}
        now={NOW}
      />,
    );
    const t = within(tile(container));

    expect(t.getByText('Out of hours')).toBeInTheDocument();
    expect(t.getByText('Outside opening hours')).toBeInTheDocument();
    expect(t.queryByText('4')).toBeNull();
  });
});

describe('Tile: accessibility and privacy', () => {
  it.each(MAIN_ENTRIES.map((e) => [e.name, e] as const))('%s has no axe violations', async (_name, e) => {
    const { container } = render(
      <ul>
        <li>
          <Tile entry={e} now={NOW} />
        </li>
      </ul>,
    );

    expect(container.querySelectorAll('[data-el="WALL-TILE"]')).toHaveLength(1);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('puts the service id only in data-service-id, never in text or any other attribute', () => {
    const { container } = render(<Tile entry={UCR_WEST} now={NOW} />);
    const html = container.innerHTML.replace(/data-service-id="[^"]*"/g, '');

    expect(container.innerHTML).toContain('data-service-id="svc-ucr-west"');
    expect(html).not.toContain('svc-ucr-west');
  });
});

// Last known (W06): the board cannot be refreshed or is too old. The figure stays
// where it is, but it is worded and styled as old, never as current. Artboard
// "BoardDown" in docs/spec/ui-screens.md.
describe('Tile: last known', () => {
  const reported = entry({ serviceId: 'svc-lk', name: 'UCR West', reportedAt: '2026-10-23T12:58:00Z' });

  it('shows the badge word Last known, the time of the figure, how old it is and the warning line', () => {
    const { container } = render(<Tile entry={reported} now={NOW} lastKnown />);
    const t = within(tile(container));

    expect(t.getByText('Last known')).toBeInTheDocument();
    expect(t.getByText('Last known 13:58')).toBeInTheDocument();
    expect(t.getByText(/14 min ago/)).toBeInTheDocument();
    expect(t.getByText('Do not rely on this. Phone to confirm.')).toBeInTheDocument();
  });

  it('keeps the number as last known, with its unit and bar', () => {
    const { container } = render(<Tile entry={reported} now={NOW} lastKnown />);
    const t = within(tile(container));

    expect(t.getByText('4')).toBeInTheDocument();
    expect(t.getByText('referrals in the next 2 hrs')).toBeInTheDocument();
    expect(t.getByText('Used 4 of 8')).toBeInTheDocument();
  });

  it('is not styled or worded as current: no status word, no "Updated", no next due, no comment', () => {
    const { container } = render(<Tile entry={{ ...reported, comment: 'Response time about 1 hr 20' }} now={NOW} lastKnown />);
    const el = tile(container);

    expect(el).toHaveAttribute('data-status', 'last-known');
    expect(el.querySelector('[data-status="last-known"][data-shape="dashed-circle"]')).not.toBeNull();
    expect(el.className).toMatch(/notUpdated/);
    expect(el.textContent).not.toMatch(/Accepting|Limited|Not accepting|Over capacity|Out of hours|Not updated/);
    expect(el.textContent).not.toMatch(/Updated|next due/);
    expect(el.textContent).not.toContain('Response time about 1 hr 20');
  });

  it('shows the warning line in bold', () => {
    const { container } = render(<Tile entry={reported} now={NOW} lastKnown />);

    expect(within(tile(container)).getByText('Do not rely on this. Phone to confirm.').tagName).toBe('STRONG');
  });

  it.each(MAIN_ENTRIES.map((e) => [e.status, e] as const))('a %s service is shown as Last known', (_status, e) => {
    const { container } = render(<Tile entry={e} now={NOW} lastKnown />);
    const el = tile(container);

    expect(within(el).getByText('Last known')).toBeInTheDocument();
    expect(el).toHaveAttribute('data-status', 'last-known');
    expect(el.textContent).toContain('Do not rely on this. Phone to confirm.');
  });

  it('keeps a zero as last known, and an over-capacity figure as +N', () => {
    const closed = MAIN_ENTRIES.find((e) => e.status === 'not-accepting');
    const over = MAIN_ENTRIES.find((e) => e.status === 'over-capacity');
    if (!closed || !over) throw new Error('fixture');

    const zero = render(<Tile entry={closed} now={NOW} lastKnown />);
    expect(within(tile(zero.container)).getByText('0')).toBeInTheDocument();
    const surge = render(<Tile entry={over} now={NOW} lastKnown />);
    expect(within(tile(surge.container)).getByText('+2')).toBeInTheDocument();
  });

  it('shows ? and Phone to confirm for a service that was not updated, as before', () => {
    const { container } = render(<Tile entry={VIRTUAL_WARD} now={NOW} lastKnown />);
    const t = within(tile(container));

    expect(t.getByText('?')).toBeInTheDocument();
    expect(t.getByText('Phone to confirm')).toBeInTheDocument();
    expect(t.queryByText('3')).toBeNull();
  });

  it('does not repeat an out-of-hours claim that may have changed: it shows ? and Phone to confirm', () => {
    const closedHours = entry({ serviceId: 'svc-oh', name: 'Night service', status: 'out-of-hours', effectiveAvailable: null, used: null });
    const { container } = render(<Tile entry={closedHours} now={NOW} lastKnown />);
    const t = within(tile(container));

    expect(t.getByText('?')).toBeInTheDocument();
    expect(t.getByText('Phone to confirm')).toBeInTheDocument();
    expect(t.queryByText('Outside opening hours')).toBeNull();
  });

  it('says No figure reported yet, and no Last known time, when the service never reported', () => {
    const none = entry({ serviceId: 'svc-none', name: 'New service', status: 'not-updated', reportedAt: null, used: null, effectiveAvailable: null });
    const { container } = render(<Tile entry={none} now={NOW} lastKnown />);
    const el = tile(container);

    expect(within(el).getByText('No figure reported yet')).toBeInTheDocument();
    expect(el.textContent).not.toMatch(/Last known \d/);
  });

  it('gives the age as well as the time, so a figure from yesterday is not read as today', () => {
    const yesterday = entry({ serviceId: 'svc-y', name: 'Old', reportedAt: '2026-10-22T12:58:00Z' });
    const { container } = render(<Tile entry={yesterday} now={NOW} lastKnown />);
    const el = tile(container);

    expect(el.textContent).toContain('Last known 13:58');
    expect(el.textContent).toContain('24 hrs 14 min ago');
  });

  it('measures the age on instants across the autumn clock change: 01:30 BST to 01:40 GMT is 1 hr 10 min', () => {
    const e = entry({ serviceId: 'svc-c', name: 'Clock', reportedAt: '2026-10-25T00:30:00Z' });
    const { container } = render(<Tile entry={e} now={new Date('2026-10-25T01:40:00Z')} lastKnown />);
    const el = tile(container);

    expect(el.textContent).toContain('Last known 01:30');
    expect(el.textContent).toContain('1 hr 10 min ago');
  });

  it('measures the age on instants across the spring clock change: 00:58 GMT to 02:01 BST is 3 min', () => {
    const e = entry({ serviceId: 'svc-s', name: 'Clock', reportedAt: '2026-03-29T00:58:00Z' });
    const { container } = render(<Tile entry={e} now={new Date('2026-03-29T01:01:00Z')} lastKnown />);
    const el = tile(container);

    expect(el.textContent).toContain('Last known 00:58');
    expect(el.textContent).toContain('3 min ago');
  });

  it('is a normal current tile when lastKnown is not set', () => {
    const { container } = render(<Tile entry={UCR_WEST} now={NOW} />);

    expect(tile(container)).toHaveAttribute('data-status', 'accepting');
    expect(tile(container).textContent).not.toContain('Last known');
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <ul>
        <li>
          <Tile entry={reported} now={NOW} lastKnown />
        </li>
      </ul>,
    );

    expect(container.querySelectorAll('[data-el="WALL-TILE"]')).toHaveLength(1);
    expect(within(tile(container)).getByText('Last known')).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
