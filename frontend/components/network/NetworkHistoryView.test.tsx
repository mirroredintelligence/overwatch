import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { networkBffHandlers, resetNetworkBff } from '@/test/msw/handlers/networkBff';
import { server } from '@/test/msw/server';
import { NetworkHistoryView } from './NetworkHistoryView';

// TEN-070 (docs/design/network-ui.md, NetworkHistory): a read-only list of what members that left, or that
// stopped sharing, had shared. It is history: the services are not on the live board, and it says so.

describe('NetworkHistoryView', () => {
  it('says it is history, not the live board, and lists each ended service with when and why', async () => {
    server.use(
      http.get('/api/bff/network/directory', ({ request }) => {
        const history = new URL(request.url).searchParams.get('history') === 'true';
        return HttpResponse.json({
          entries: history
            ? [
                { rowRef: 'lst-0090', organisationName: 'Sample Area D', serviceName: 'Former service', category: 'inpatient-beds', active: true, source: 'manual', contactLabel: null, contactPhone: null, location: null, openingHours: [], presentation: 'shown', endedAt: '2026-10-01T09:00:00+00:00', endReason: 'left' },
                { rowRef: 'lst-0091', organisationName: 'Sample Area B', serviceName: 'Stopped service', category: 'reablement', active: true, source: 'manual', contactLabel: null, contactPhone: null, location: null, openingHours: [], presentation: 'shown', endedAt: '2026-10-05T09:00:00+00:00', endReason: 'grant-ended' },
                { rowRef: 'lst-0092', organisationName: 'Sample Area B', serviceName: 'Changed service', category: 'reablement', active: true, source: 'manual', contactLabel: null, contactPhone: null, location: null, openingHours: [], presentation: 'shown', endedAt: '2026-10-06T09:00:00+00:00', endReason: 'replaced' },
              ]
            : [],
          systemName: 'a',
          pathwayName: 'b',
          timeZone: 'Europe/London',
        });
      }),
      ...networkBffHandlers,
    );
    resetNetworkBff();
    const { container } = render(<NetworkHistoryView ownHref="/advisor/board" />);
    expect(await screen.findByText('This is history. These services are not on the live board.')).toBeInTheDocument();
    await waitFor(() => expect(container.querySelectorAll('[data-el="NET-BOARD-ROW"]')).toHaveLength(2));
    const rows = Array.from(container.querySelectorAll<HTMLElement>('[data-el="NET-BOARD-ROW"]'));
    expect(rows).toHaveLength(2);
    expect(within(rows[0]!).getByText('Former service')).toBeInTheDocument();
    expect(within(rows[0]!).getByText('Left the network on 1 October 2026')).toBeInTheDocument();
    expect(within(rows[1]!).getByText('Stopped sharing on 5 October 2026')).toBeInTheDocument();
    expect(screen.queryByText('Changed service')).toBeNull();
    expect(screen.getByRole('region', { name: 'Which board you are viewing' })).toHaveTextContent('Showing: Network, Sample Network');
  });

  it('says nothing has ended when there is no history, never an empty page', async () => {
    server.use(http.get('/api/bff/network/directory', () => HttpResponse.json({ entries: [], systemName: 'a', pathwayName: 'b', timeZone: 'Europe/London' })), ...networkBffHandlers);
    render(<NetworkHistoryView ownHref="/advisor/board" />);
    expect(await screen.findByText('No organisation has left or stopped sharing.')).toBeInTheDocument();
  });

  it('is "not available" when the read is refused, and says it could not read it when the read fails', async () => {
    server.use(http.get('/api/bff/network/directory', () => HttpResponse.json({ code: 'not-found' }, { status: 404 })), ...networkBffHandlers);
    const refused = render(<NetworkHistoryView ownHref="/advisor/board" />);
    expect(await screen.findByText('Network view not available')).toBeInTheDocument();
    refused.unmount();
    server.use(http.get('/api/bff/network/directory', () => HttpResponse.json({ code: 'exception' }, { status: 503 })));
    render(<NetworkHistoryView ownHref="/advisor/board" />);
    expect(await screen.findByText('The history could not be read. Try again shortly.')).toBeInTheDocument();
  });

  it('shows each ended service with a Last known tag, and no figure the data does not carry', async () => {
    server.use(
      http.get('/api/bff/network/directory', () =>
        HttpResponse.json({
          entries: [
            { rowRef: 'lst-0090', organisationName: 'Sample Area D', serviceName: 'Former service', category: 'inpatient-beds', active: true, source: 'manual', contactLabel: null, contactPhone: null, location: null, openingHours: [], presentation: 'shown', endedAt: '2026-10-01T09:00:00+00:00', endReason: 'left' },
          ],
          systemName: 'a',
          pathwayName: 'b',
          timeZone: 'Europe/London',
        }),
      ),
      ...networkBffHandlers,
    );
    const { container } = render(<NetworkHistoryView ownHref="/advisor/board" />);
    await waitFor(() => expect(container.querySelectorAll('[data-el="NET-BOARD-ROW"]')).toHaveLength(1));
    const row = container.querySelector<HTMLElement>('[data-el="NET-BOARD-ROW"]')!;
    expect(within(row).getByText('Last known')).toBeInTheDocument();
  });

  it('filters the history to the services that left, or stopped sharing, and back to all', async () => {
    const user = userEvent.setup();
    server.use(
      http.get('/api/bff/network/directory', () =>
        HttpResponse.json({
          entries: [
            { rowRef: 'lst-0090', organisationName: 'Sample Area D', serviceName: 'Former service', category: 'inpatient-beds', active: true, source: 'manual', contactLabel: null, contactPhone: null, location: null, openingHours: [], presentation: 'shown', endedAt: '2026-10-01T09:00:00+00:00', endReason: 'left' },
            { rowRef: 'lst-0091', organisationName: 'Sample Area B', serviceName: 'Stopped service', category: 'reablement', active: true, source: 'manual', contactLabel: null, contactPhone: null, location: null, openingHours: [], presentation: 'shown', endedAt: '2026-10-05T09:00:00+00:00', endReason: 'grant-ended' },
          ],
          systemName: 'a',
          pathwayName: 'b',
          timeZone: 'Europe/London',
        }),
      ),
      ...networkBffHandlers,
    );
    const { container } = render(<NetworkHistoryView ownHref="/advisor/board" />);
    await waitFor(() => expect(container.querySelectorAll('[data-el="NET-BOARD-ROW"]')).toHaveLength(2));
    const all = screen.getByRole('button', { name: 'All' });
    const left = screen.getByRole('button', { name: 'Left the network' });
    const stopped = screen.getByRole('button', { name: 'Stopped sharing' });
    expect(all).toHaveAttribute('aria-pressed', 'true');
    expect(left).toHaveAttribute('aria-pressed', 'false');
    expect(stopped).toHaveAttribute('aria-pressed', 'false');

    await user.click(left);
    expect(left).toHaveAttribute('aria-pressed', 'true');
    expect(all).toHaveAttribute('aria-pressed', 'false');
    const leftRows = Array.from(container.querySelectorAll<HTMLElement>('[data-el="NET-BOARD-ROW"]'));
    expect(leftRows).toHaveLength(1);
    expect(within(leftRows[0]!).getByText('Former service')).toBeInTheDocument();

    await user.click(stopped);
    const stoppedRows = Array.from(container.querySelectorAll<HTMLElement>('[data-el="NET-BOARD-ROW"]'));
    expect(stoppedRows).toHaveLength(1);
    expect(within(stoppedRows[0]!).getByText('Stopped service')).toBeInTheDocument();

    await user.click(all);
    expect(container.querySelectorAll('[data-el="NET-BOARD-ROW"]')).toHaveLength(2);
  });

  it('says no service matches a filter that has nothing in it, and how to clear it', async () => {
    const user = userEvent.setup();
    server.use(
      http.get('/api/bff/network/directory', () =>
        HttpResponse.json({
          entries: [
            { rowRef: 'lst-0090', organisationName: 'Sample Area D', serviceName: 'Former service', category: 'inpatient-beds', active: true, source: 'manual', contactLabel: null, contactPhone: null, location: null, openingHours: [], presentation: 'shown', endedAt: '2026-10-01T09:00:00+00:00', endReason: 'left' },
          ],
          systemName: 'a',
          pathwayName: 'b',
          timeZone: 'Europe/London',
        }),
      ),
      ...networkBffHandlers,
    );
    render(<NetworkHistoryView ownHref="/advisor/board" />);
    await screen.findByText('Former service');
    await user.click(screen.getByRole('button', { name: 'Stopped sharing' }));
    expect(screen.getByText('No services match this filter')).toBeInTheDocument();
    expect(screen.getByText('Clear the filter to see all organisations.')).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    server.use(...networkBffHandlers);
    const { container } = render(<NetworkHistoryView ownHref="/advisor/board" />);
    await screen.findByText('Former service');
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
