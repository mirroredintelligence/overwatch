import { render, screen, waitFor, within } from '@testing-library/react';
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

  it('has no axe violations', async () => {
    server.use(...networkBffHandlers);
    const { container } = render(<NetworkHistoryView ownHref="/advisor/board" />);
    await screen.findByText('Former service');
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
