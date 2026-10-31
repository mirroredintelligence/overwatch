import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { BOARD_BODY, boardEntry, NETWORK_NOW, OWN_ORGANISATION } from '@/test/fixtures/network';
import { parseBoard, parsePhones } from '@/lib/network/parse';
import { PHONES_BODY } from '@/test/fixtures/network';
import type { NetworkBoard as Board } from '@/lib/network/types';
import { NetworkBoard } from './NetworkBoard';

// TEN-070 (docs/design/network-ui.md section 4): the network capacity board. The same look as the wall
// board, read only, each row labelled with its organisation, the viewer's own marked in words, no private
// figure, no action but the service line, and a statement of what the page is in every state.

const board = parseBoard(BOARD_BODY, 'backend');
const lines = Object.fromEntries(parsePhones(PHONES_BODY, 'backend').phones.map((p) => [p.rowRef, { label: p.contactLabel, phone: p.contactPhone }]));
const SWITCH = { ownHref: '/advisor/board', networkHref: '/network/board' };
const LAST_KNOWN = { mode: 'last-known' as const, reason: 'offline' as const, since: '2026-10-23T13:05:00Z', asOf: NETWORK_NOW, now: '2026-10-23T13:20:00Z', ageMs: 8 * 60_000 };

function show(over: Partial<Parameters<typeof NetworkBoard>[0]> = {}, data: Board = board) {
  return render(<NetworkBoard board={data} networkName="Sample Network" ownOrganisation={OWN_ORGANISATION} serviceLines={lines} switchTo={SWITCH} {...over} />);
}

const tiles = (container: HTMLElement) => Array.from(container.querySelectorAll<HTMLElement>('[data-el="NET-BOARD-TILE"]'));

describe('the heading, the scope and the counts', () => {
  it('has the network’s heading, "{Network name} capacity", and the scope header that says it is the network', () => {
    show();
    expect(screen.getByRole('heading', { level: 1, name: 'Sample Network capacity' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Which board you are viewing' })).toHaveTextContent('Showing: Network, Sample Network');
    expect(screen.getByRole('link', { name: 'Network' })).toHaveAttribute('aria-current', 'page');
  });

  it('counts the services and the organisations', () => {
    show();
    expect(screen.getByText('4 services from 3 organisations')).toBeInTheDocument();
  });

  it('says "1 service from 1 organisation" for one of each', () => {
    show({}, { ...board, entries: [board.entries[0]!] });
    expect(screen.getByText('1 service from 1 organisation')).toBeInTheDocument();
  });

  it('has the footer: no patient information, and not ranked', () => {
    show();
    expect(screen.getByText('No patient information on this screen')).toBeInTheDocument();
    expect(screen.getByText('Figures are reported by each organisation. Sorted by category, then organisation. Not ranked.')).toBeInTheDocument();
  });
});

describe('read only', () => {
  it('shows the read-only note once, and no action but the service line', () => {
    const { container } = show();
    expect(screen.getAllByText('Read only')).toHaveLength(1);
    expect(container.querySelectorAll('[data-el="SCOPE-READONLY-NOTE"]')).toHaveLength(1);
    const text = container.textContent ?? '';
    for (const word of ['Request booking', 'I phoned', 'They declined', 'Subscribe', 'Escalate']) expect(text).not.toContain(word);
    // The buttons are the filters and the view toggle only; each row's one control is the link.
    for (const tile of tiles(container)) expect(within(tile).queryAllByRole('button')).toEqual([]);
  });

  it('shows no comment line, no pending chip and no next-due time on any row', () => {
    const { container } = show();
    expect(container.querySelector('[data-el="WALL-TILE-COMMENT"],[data-el="WALL-TILE-PENDING"]')).toBeNull();
    expect(container.textContent).not.toMatch(/next due|pending/i);
  });
});

describe('the tiles', () => {
  it('shows a tile for each service in the order the back end sent them, with the organisation under the name', () => {
    const { container } = show();
    expect(tiles(container).map((t) => t.getAttribute('data-service-ref'))).toEqual(['lst-0001', 'lst-0002', 'lst-0003', 'lst-0004']);
    const first = tiles(container)[0]!;
    expect(within(first).getByRole('heading', { name: 'UCR West' })).toBeInTheDocument();
    expect(within(first).getByText('Sample Area A')).toBeInTheDocument();
    expect(within(first).getByText('Urgent community response')).toBeInTheDocument();
  });

  it('marks the viewer’s own organisation in words, and no other', () => {
    const { container } = show();
    expect(within(tiles(container)[0]!).getByText('Your organisation')).toBeInTheDocument();
    expect(within(tiles(container)[1]!).queryByText('Your organisation')).toBeNull();
    expect(screen.getAllByText('Your organisation')).toHaveLength(1);
  });

  it('marks none when the viewer’s own organisation is not known', () => {
    show({ ownOrganisation: null });
    expect(screen.queryByText('Your organisation')).toBeNull();
  });

  it('shows the status as a word and a shape, the figure, the unit, the bar and the age', () => {
    const { container } = show();
    const first = tiles(container)[0]!;
    expect(first.querySelector('[data-status="accepting"]')).not.toBeNull();
    expect(within(first).getByText('Accepting')).toBeInTheDocument();
    expect(within(first).getByText('4')).toBeInTheDocument();
    expect(within(first).getByText('beds')).toBeInTheDocument();
    expect(within(first).getByText('Used 2 of 6')).toBeInTheDocument();
    expect(within(first).getByText('Updated 4 min ago')).toBeInTheDocument();
  });

  it('shows a late figure as Not updated, with a "?" and "Phone to confirm", never the old number', () => {
    const { container } = show();
    const late = tiles(container)[2]!;
    expect(within(late).getByText('Not updated')).toBeInTheDocument();
    expect(within(late).getByText('?')).toBeInTheDocument();
    expect(within(late).getByText('Phone to confirm')).toBeInTheDocument();
    expect(within(late).getByText('Not updated for 4 hrs 10 min · was due 12:00')).toBeInTheDocument();
    expect(within(late).queryByText('3')).toBeNull();
  });

  it('shows a paused listing as Not updated with its own words, a "?" and no new status word', () => {
    const { container } = show();
    const paused = tiles(container)[3]!;
    expect(within(paused).getByText('Not updated')).toBeInTheDocument();
    expect(within(paused).getByText('?')).toBeInTheDocument();
    expect(within(paused).getByText('Not available on the network. Phone to confirm.')).toBeInTheDocument();
    expect(paused.textContent).not.toMatch(/Unavailable|Paused/);
  });

  it('shows over capacity as the amount over, as the wall does', () => {
    const over = parseBoard({ ...BOARD_BODY, entries: [boardEntry({ status: 'over-capacity', over_by: 2, used: 8, established: 6, effective_available: 0 })] }, 'backend');
    const { container } = show({}, over);
    expect(within(tiles(container)[0]!).getByText('+2')).toBeInTheDocument();
  });
});

describe('the service line', () => {
  it('is a link to phone the service, when the organisation shared one', () => {
    const { container } = show();
    const link = within(tiles(container)[0]!).getByRole('link', { name: 'Phone UCR West on 01632 960010' });
    expect(link).toHaveAttribute('href', 'tel:01632960010');
    expect(link).toHaveAttribute('data-el', 'NET-BOARD-PHONE-LINK');
    expect(link).toHaveTextContent('01632 960010');
  });

  it('says "No number shared" when the organisation shared none, with no link', () => {
    const { container } = show();
    const second = tiles(container)[1]!;
    expect(within(second).getByText('No number shared')).toBeInTheDocument();
    expect(within(second).queryByRole('link')).toBeNull();
  });

  it('says the numbers could not be read, once, when the service lines were not loaded, and invents none', () => {
    const { container } = show({ serviceLines: null });
    expect(screen.getByText('Service line numbers could not be loaded. Phone to confirm.')).toBeInTheDocument();
    expect(container.querySelector('[data-el="NET-BOARD-PHONE-LINK"]')).toBeNull();
    expect(container.textContent).not.toContain('No number shared');
  });
});

describe('the organisation filter and the view toggle', () => {
  it('has "All organisations" first, then the viewer’s own, then the others alphabetically, each a pressed-state chip', () => {
    show();
    const chips = screen.getAllByRole('button', { pressed: undefined }).filter((b) => b.getAttribute('aria-pressed') !== null);
    const orgChips = chips.filter((b) => ['NET-BOARD-ORG-ALL-CHIP', 'NET-BOARD-ORG-CHIP'].includes(b.getAttribute('data-el') ?? ''));
    expect(orgChips.map((b) => b.textContent)).toEqual(['All organisations', 'Sample Area A', 'Sample Area B', 'Sample Area D']);
    expect(orgChips[0]).toHaveAttribute('aria-pressed', 'true');
    expect(orgChips[1]).toHaveAttribute('aria-pressed', 'false');
    expect(orgChips[0]).toHaveAttribute('data-el', 'NET-BOARD-ORG-ALL-CHIP');
    expect(orgChips[2]).toHaveAttribute('data-org-ref', 'org-3');
  });

  it('filters in place, over the rows it already has, and says nothing is selected again with All', async () => {
    const user = userEvent.setup();
    const { container } = show();
    await user.click(screen.getByRole('button', { name: 'Sample Area B' }));
    expect(tiles(container).map((t) => t.getAttribute('data-service-ref'))).toEqual(['lst-0002', 'lst-0003']);
    expect(screen.getByRole('button', { name: 'Sample Area B' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'All organisations' })).toHaveAttribute('aria-pressed', 'false');
    await user.click(screen.getByRole('button', { name: 'All organisations' }));
    expect(tiles(container)).toHaveLength(4);
  });

  it('says no service matches when the chosen organisation is no longer on the board', async () => {
    const user = userEvent.setup();
    const view = show();
    await user.click(screen.getByRole('button', { name: 'Sample Area D' }));
    view.rerender(
      <NetworkBoard board={{ ...board, entries: board.entries.slice(0, 3) }} networkName="Sample Network" ownOrganisation={OWN_ORGANISATION} serviceLines={lines} switchTo={SWITCH} />,
    );
    expect(screen.getByText('No services match this filter')).toBeInTheDocument();
    expect(screen.getByText('Clear the filter to see all organisations.')).toBeInTheDocument();
  });

  it('switches between tiles and a list of the same services in the same order', async () => {
    const user = userEvent.setup();
    const { container } = show();
    expect(screen.getByRole('button', { name: 'Tiles' })).toHaveAttribute('aria-pressed', 'true');
    await user.click(screen.getByRole('button', { name: 'List' }));
    expect(screen.getByRole('button', { name: 'List' })).toHaveAttribute('aria-pressed', 'true');
    expect(tiles(container)).toHaveLength(0);
    const rows = Array.from(container.querySelectorAll<HTMLElement>('[data-el="NET-BOARD-ROW"]'));
    expect(rows.map((r) => r.getAttribute('data-service-ref'))).toEqual(['lst-0001', 'lst-0002', 'lst-0003', 'lst-0004']);
    expect(within(rows[0]!).getByText('Your organisation')).toBeInTheDocument();
    expect(within(rows[0]!).getByText('Updated 4 min ago')).toBeInTheDocument();
    expect(within(rows[2]!).getByText('Not updated for 4 hrs 10 min · was due 12:00')).toBeInTheDocument();
  });
});

describe('an empty network', () => {
  it('says no services are shared yet, naming the network', () => {
    show({}, { ...board, entries: [] });
    expect(screen.getByText('No services are shared yet')).toBeInTheDocument();
    expect(screen.getByText('When organisations share their capacity with Sample Network, their services appear here.')).toBeInTheDocument();
  });
});

describe('what an organisation’s state says', () => {
  it('says updates from an organisation are delayed when all its services are Not updated, above its rows', () => {
    const delayed = parseBoard(
      {
        ...BOARD_BODY,
        entries: [
          boardEntry({ row_ref: 'lst-0010', organisation_name: 'Sample Area B', status: 'not-updated', stale_warning: true, reported_at: '2026-10-23T09:00:00+00:00', was_due_at: '2026-10-23T11:00:00+00:00' }),
          boardEntry({ row_ref: 'lst-0011', organisation_name: 'Sample Area B', service_name: 'Second', status: 'not-updated', stale_warning: true, reported_at: '2026-10-23T09:00:00+00:00', was_due_at: '2026-10-23T11:00:00+00:00' }),
          boardEntry({ row_ref: 'lst-0012', organisation_name: OWN_ORGANISATION, service_name: 'Fine' }),
        ],
      },
      'backend',
    );
    show({}, delayed);
    expect(screen.getByText('Updates from Sample Area B are delayed. Its services show Not updated.')).toBeInTheDocument();
    expect(screen.queryByText(/Updates from Sample Area A/)).toBeNull();
  });

  it('says nothing about an organisation that has one late service and one current', () => {
    show();
    expect(screen.queryByText(/are delayed/)).toBeNull();
  });

  it('says which organisations stopped sharing, and when, above the board, with the way to the history', () => {
    show({ stopped: [{ organisation: 'Sample Area D', date: '2026-10-01T09:00:00+00:00' }, { organisation: 'Sample Area E', date: null }], historyHref: '/network/history' });
    expect(screen.getByText('No longer shown: Sample Area D, Sample Area E.')).toBeInTheDocument();
    expect(screen.getByText('Sample Area D stopped sharing on 1 October 2026.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'See history' })).toHaveAttribute('href', '/network/history');
  });
});

describe('last known', () => {
  it('says the board is offline since a time, and that the figures may be wrong, and offers to try again', async () => {
    const onRetry = vi.fn();
    const user = userEvent.setup();
    show({ lastKnown: LAST_KNOWN, onRetry });
    const panel = screen.getByRole('alert');
    expect(panel).toHaveAttribute('data-el', 'NET-STATE-PANEL');
    expect(panel).toHaveTextContent('Network board offline since 14:05');
    expect(panel).toHaveTextContent('Figures are the last known and may be wrong. Use the whiteboard and phone process.');
    await user.click(within(panel).getByRole('button', { name: 'Try again' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('keeps the figures as Last known, with the time of the last figure, and never as current', () => {
    const { container } = show({ lastKnown: LAST_KNOWN });
    const first = tiles(container)[0]!;
    expect(within(first).getByText('Last known')).toBeInTheDocument();
    expect(first.getAttribute('data-status')).toBe('last-known');
    expect(within(first).getByText('Do not rely on this. Phone to confirm.')).toBeInTheDocument();
    expect(within(first).getByText(/Last known 14:08/)).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/Updated \d+ min ago/);
  });

  it('keeps the scope header, saying it is the network, and the read-only note', () => {
    show({ lastKnown: LAST_KNOWN });
    expect(screen.getByText('Showing: Network, Sample Network')).toBeInTheDocument();
    expect(screen.getByText('Read only')).toBeInTheDocument();
  });
});

describe('no tenant, grant or source id on the page', () => {
  it('has nothing shaped like one, in the text or the attributes', () => {
    const { container } = show();
    expect(container.innerHTML).not.toMatch(/trust-[a-z]|tenant|sourceTenant|source_tenant|grant|net-sample/i);
  });

  it('has no axe violations', async () => {
    const { container } = show();
    expect((await runAxe(container)).violations).toEqual([]);
  });

  it('has none in the list, nor last known', async () => {
    const user = userEvent.setup();
    const { container } = show({ lastKnown: LAST_KNOWN, stopped: [{ organisation: 'Sample Area D', date: null }], historyHref: '/network/history' });
    await user.click(screen.getByRole('button', { name: 'List' }));
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
