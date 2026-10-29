import { render, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import {
  CONFIRMED_TILE,
  entry,
  MAIN_ENTRIES,
  NOW,
  PENDING_TILE,
  QUIET_ENTRIES,
  SURGE_ENTRIES,
  UCR_WEST,
  VIRTUAL_WARD,
} from '@/test/fixtures/board';
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

describe('Tile: over capacity (W07)', () => {
  const over = MAIN_ENTRIES.find((e) => e.status === 'over-capacity');
  if (!over) throw new Error('fixture has no over-capacity service');

  it('shows the word Over capacity, +2, the unit as sent, "Used 14 of 12" and the comment', () => {
    const { container } = render(<Tile entry={over} now={NOW} />);
    const t = within(tile(container));

    expect(t.getByText('Over capacity')).toBeInTheDocument();
    expect(container.querySelector('[data-el="WALL-TILE-NUMBER"]')).toHaveTextContent('+2');
    expect(t.getByText('over established capacity')).toBeInTheDocument();
    expect(t.getByText('Used 14 of 12')).toBeInTheDocument();
    expect(t.getByText('Escalation in place')).toBeInTheDocument();
  });

  it('is told apart by a word and a shape (the diamond), not by colour alone', () => {
    const { container } = render(<Tile entry={over} now={NOW} />);
    const el = tile(container);

    expect(el).toHaveAttribute('data-status', 'over-capacity');
    expect(el.className).toMatch(/overCapacity/);
    expect(el.querySelector('[data-status="over-capacity"][data-shape="diamond"]')).toHaveTextContent('Over capacity');
  });

  it('fills the bar to 100% however far over it is', () => {
    const { container } = render(<Tile entry={over} now={NOW} />);

    expect(container.querySelector<HTMLElement>('[data-bar-fill]')?.style.width).toBe('100%');
  });

  it('shows the pending count apart: +4 stays +4 and the bar label gains " · 1 pending"', () => {
    const surge = SURGE_ENTRIES.find((e) => e.serviceId === 'svc-hospital-at-home');
    if (!surge) throw new Error('fixture');
    const { container } = render(<Tile entry={surge} now={NOW} />);
    const t = within(tile(container));

    expect(container.querySelector('[data-el="WALL-TILE-NUMBER"]')).toHaveTextContent('+4');
    expect(t.getByText('Used 16 of 12 · 1 pending')).toBeInTheDocument();
    expect(container.querySelector('[data-el="WALL-TILE-PENDING"]')).toHaveTextContent('1 pending');
  });

  it('uses the unit label exactly as the back end sent it, singular or plural', () => {
    const { container } = render(<Tile entry={{ ...over, unitLabel: 'bed over established capacity' }} now={NOW} />);

    expect(within(tile(container)).getByText('bed over established capacity')).toBeInTheDocument();
  });
});

describe('Tile: over capacity without an over-by count (W07)', () => {
  const base = entry({
    serviceId: 'svc-o',
    name: 'Over',
    status: 'over-capacity',
    effectiveAvailable: null,
    overBy: null,
    unitLabel: 'over established capacity',
  });

  it('works +N out from used and established when the back end sends no over-by', () => {
    const { container } = render(<Tile entry={{ ...base, used: 14, established: 12 }} now={NOW} />);

    expect(container.querySelector('[data-el="WALL-TILE-NUMBER"]')).toHaveTextContent('+2');
  });

  it('shows ? and Phone to confirm, never a guessed number, when it cannot work it out', () => {
    const { container } = render(<Tile entry={{ ...base, used: null, established: 12 }} now={NOW} />);

    expect(container.querySelector('[data-el="WALL-TILE-NUMBER"]')).toHaveTextContent('?');
    expect(within(tile(container)).getByText('Phone to confirm')).toBeInTheDocument();
    expect(within(tile(container)).getByText('Over capacity')).toBeInTheDocument();
  });

  it('fills the bar when nothing is established and something is used, and leaves it empty when nothing is used', () => {
    const used = render(<Tile entry={{ ...base, used: 3, established: 0 }} now={NOW} />);
    const none = render(<Tile entry={{ ...base, status: 'accepting', effectiveAvailable: 0, used: 0, established: 0 }} now={NOW} />);

    expect(used.container.querySelector<HTMLElement>('[data-bar-fill]')?.style.width).toBe('100%');
    expect(none.container.querySelector<HTMLElement>('[data-bar-fill]')?.style.width).toBe('0%');
  });
});

describe('Tile: out of hours (W07)', () => {
  const quiet = QUIET_ENTRIES[0];
  const QUIET_NOW = new Date('2026-10-24T01:40:00Z');

  it('shows the word Out of hours, a big 0, the unit as sent, "Reopens 08:00", the bar label and "Closed overnight"', () => {
    const { container } = render(<Tile entry={quiet} now={QUIET_NOW} />);
    const t = within(tile(container));

    expect(container.querySelector('[data-el="WALL-TILE-NUMBER"]')).toHaveTextContent(/^0$/);
    expect(t.getByText('referrals in the next 2 hrs')).toBeInTheDocument();
    expect(t.getByText('Reopens 08:00')).toBeInTheDocument();
    // The badge word and the bar label.
    expect(t.getAllByText('Out of hours')).toHaveLength(2);
    expect(t.getByText('Closed overnight')).toBeInTheDocument();
  });

  it('is told apart from Not accepting by its word and its own shape (the moon)', () => {
    const { container } = render(<Tile entry={quiet} now={QUIET_NOW} />);
    const el = tile(container);

    expect(el).toHaveAttribute('data-status', 'out-of-hours');
    expect(el.className).toMatch(/outOfHours/);
    expect(el.querySelector('[data-status="out-of-hours"][data-shape="moon"]')).toHaveTextContent('Out of hours');
    expect(el.textContent).not.toContain('Not accepting');
  });

  it('fills the bar to 100%', () => {
    const { container } = render(<Tile entry={quiet} now={QUIET_NOW} />);

    expect(container.querySelector<HTMLElement>('[data-bar-fill]')?.style.width).toBe('100%');
  });

  it('shows 0 whatever free count the back end held, never a number that could be read as places', () => {
    const { container } = render(
      <Tile entry={{ ...quiet, effectiveAvailable: 4, used: 4 }} now={QUIET_NOW} />,
    );
    const t = within(tile(container));

    expect(container.querySelector('[data-el="WALL-TILE-NUMBER"]')).toHaveTextContent(/^0$/);
    expect(t.queryByText('4')).toBeNull();
    expect(t.queryByText(/Used/)).toBeNull();
  });

  it('gives the reopening time in London time: 07:00 UTC in summer is 08:00, in winter it is 07:00', () => {
    const summer = render(<Tile entry={quiet} now={QUIET_NOW} />);
    expect(within(tile(summer.container)).getByText('Reopens 08:00')).toBeInTheDocument();

    const winter = render(
      <Tile entry={{ ...quiet, nextDueAt: '2026-10-26T08:00:00Z' }} now={new Date('2026-10-26T01:40:00Z')} />,
    );
    expect(within(tile(winter.container)).getByText('Reopens 08:00')).toBeInTheDocument();
    const winterEarly = render(
      <Tile entry={{ ...quiet, nextDueAt: '2026-10-26T07:00:00Z' }} now={new Date('2026-10-26T01:40:00Z')} />,
    );
    expect(within(tile(winterEarly.container)).getByText('Reopens 07:00')).toBeInTheDocument();
  });

  it('says which day when the service does not reopen today', () => {
    const { container } = render(<Tile entry={quiet} now={NOW} />);

    // Friday 14:12 London, reopening Saturday 08:00.
    expect(within(tile(container)).getByText('Reopens 08:00 tomorrow')).toBeInTheDocument();
  });

  it('leaves out the reopening line, and nothing else, when the back end sends no next time', () => {
    const { container } = render(<Tile entry={{ ...quiet, nextDueAt: null }} now={QUIET_NOW} />);
    const t = within(tile(container));

    expect(t.queryByText(/Reopens/)).toBeNull();
    expect(t.getAllByText('Out of hours')).toHaveLength(2);
    expect(t.getByText('Closed overnight')).toBeInTheDocument();
  });

  it('does not show the service comment, which may describe hours that no longer apply', () => {
    const { container } = render(<Tile entry={{ ...quiet, comment: 'Admissions until 06:00' }} now={QUIET_NOW} />);

    expect(tile(container).textContent).not.toContain('Admissions until 06:00');
  });

  it('shows no "Updated", "next due" or "Not updated" wording', () => {
    const { container } = render(<Tile entry={quiet} now={QUIET_NOW} />);

    expect(tile(container).textContent).not.toMatch(/Updated|next due|Not updated/);
  });
});

describe('Tile: pending bookings (W07, "TileStates")', () => {
  function chip(container: HTMLElement): HTMLElement | null {
    return container.querySelector<HTMLElement>('[data-el="WALL-TILE-PENDING"]');
  }

  it('step 1, a request sent: 4 stays, a "1 pending" chip shows beside it and the bar label says so', () => {
    const { container } = render(<Tile entry={PENDING_TILE} now={NOW} />);
    const t = within(tile(container));

    expect(container.querySelector('[data-el="WALL-TILE-NUMBER"]')).toHaveTextContent(/^4$/);
    expect(chip(container)).toHaveTextContent(/^1 pending$/);
    expect(t.getByText('Used 4 of 8 · 1 pending')).toBeInTheDocument();
    expect(t.getByText('referrals in the next 2 hrs')).toBeInTheDocument();
    expect(t.getByText('Updated 9 min ago · next due 14:30')).toBeInTheDocument();
  });

  it('puts the chip next to the number', () => {
    const { container } = render(<Tile entry={PENDING_TILE} now={NOW} />);

    expect(container.querySelector('[data-el="WALL-TILE-NUMBER"]')?.nextElementSibling).toBe(chip(container));
  });

  it('step 2, confirmed by text: 3, "Used 5 of 8" and no pending chip', () => {
    const { container } = render(<Tile entry={CONFIRMED_TILE} now={NOW} />);
    const t = within(tile(container));

    expect(container.querySelector('[data-el="WALL-TILE-NUMBER"]')).toHaveTextContent(/^3$/);
    expect(t.getByText('Used 5 of 8')).toBeInTheDocument();
    expect(chip(container)).toBeNull();
    expect(tile(container).textContent).not.toContain('pending');
  });

  it('step 3, declined or no reply: pending clears and the figure is back to 4', () => {
    const { container } = render(<Tile entry={{ ...PENDING_TILE, pending: 0 }} now={NOW} />);

    expect(container.querySelector('[data-el="WALL-TILE-NUMBER"]')).toHaveTextContent(/^4$/);
    expect(within(tile(container)).getByText('Used 4 of 8')).toBeInTheDocument();
    expect(chip(container)).toBeNull();
  });

  it('never reduces the available number, however many are pending', () => {
    const { container } = render(<Tile entry={{ ...PENDING_TILE, pending: 3 }} now={NOW} />);

    expect(container.querySelector('[data-el="WALL-TILE-NUMBER"]')).toHaveTextContent(/^4$/);
    expect(chip(container)).toHaveTextContent(/^3 pending$/);
    expect(within(tile(container)).getByText('Used 4 of 8 · 3 pending')).toBeInTheDocument();
  });

  it('says "pending" for one and for many, never "pendings"', () => {
    const one = render(<Tile entry={PENDING_TILE} now={NOW} />);
    const two = render(<Tile entry={{ ...PENDING_TILE, pending: 2 }} now={NOW} />);

    expect(chip(one.container)).toHaveTextContent(/^1 pending$/);
    expect(chip(two.container)).toHaveTextContent(/^2 pending$/);
  });

  it('shows it on a limited and a not-accepting tile too', () => {
    const limited = render(<Tile entry={{ ...PENDING_TILE, status: 'limited', effectiveAvailable: 1, used: 7 }} now={NOW} />);
    const full = render(<Tile entry={{ ...PENDING_TILE, status: 'not-accepting', effectiveAvailable: 0, used: 8 }} now={NOW} />);

    expect(within(tile(limited.container)).getByText('Used 7 of 8 · 1 pending')).toBeInTheDocument();
    expect(within(tile(full.container)).getByText('Used 8 of 8 · 1 pending')).toBeInTheDocument();
  });

  it('keeps a pending request visible on a service that is not updated, beside the ?', () => {
    const { container } = render(<Tile entry={{ ...VIRTUAL_WARD, pending: 1 }} now={NOW} />);
    const t = within(tile(container));

    expect(container.querySelector('[data-el="WALL-TILE-NUMBER"]')).toHaveTextContent(/^\?$/);
    expect(chip(container)).toHaveTextContent(/^1 pending$/);
    expect(t.getByText('Used ? of 10 · 1 pending')).toBeInTheDocument();
    expect(t.getByText('Phone to confirm')).toBeInTheDocument();
  });

  it('keeps a pending request visible on a service that is out of hours', () => {
    const { container } = render(
      <Tile entry={{ ...QUIET_ENTRIES[0], pending: 1 }} now={new Date('2026-10-24T01:40:00Z')} />,
    );

    expect(chip(container)).toHaveTextContent(/^1 pending$/);
    expect(within(tile(container)).getByText('Out of hours · 1 pending')).toBeInTheDocument();
    expect(container.querySelector('[data-el="WALL-TILE-NUMBER"]')).toHaveTextContent(/^0$/);
  });

  it('shows a pending count only as a word and a number, so it is not carried by colour', () => {
    const { container } = render(<Tile entry={PENDING_TILE} now={NOW} />);

    expect(chip(container)?.textContent).toBe('1 pending');
    expect(chip(container)?.className).toMatch(/pending/);
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

  it('never carries a variant into Last known: no pending chip, no Reopens, no Closed overnight, no status word', () => {
    for (const e of [...SURGE_ENTRIES, ...QUIET_ENTRIES, PENDING_TILE]) {
      const { container, unmount } = render(<Tile entry={{ ...e, pending: 2 }} now={NOW} lastKnown />);
      const el = tile(container);

      expect(el).toHaveAttribute('data-status', 'last-known');
      expect(el.className).toMatch(/notUpdated/);
      expect(el.className).not.toMatch(/outOfHours|overCapacity|accepting|limited/);
      expect(el.querySelector('[data-el="WALL-TILE-PENDING"]')).toBeNull();
      expect(el.textContent).not.toMatch(/pending|Reopens|Closed overnight|Outside opening hours|Escalation/);
      expect(el.textContent).not.toMatch(/Over capacity|Out of hours|Not accepting|Limited|Accepting|Not updated/);
      expect(el.textContent).toContain('Do not rely on this. Phone to confirm.');
      unmount();
    }
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
