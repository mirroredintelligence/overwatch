import { act, configure, render, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FakeStream } from '@/test/fakeStream';
import { BOARD_BODY, boardEntry } from '@/test/fixtures/network';
import { networkBffHandlers, resetNetworkBff, seenNetworkBff } from '@/test/msw/handlers/networkBff';
import { server } from '@/test/msw/server';
import { parseBoard } from '@/lib/network/parse';
import { NetworkBoardView } from './NetworkBoardView';

// TEN-070: the network board page. It reads the networks, then the board and the service lines of the
// one network, keeps them current from the network stream, and says what it is in every state.

configure({ asyncUtilTimeout: 4000 });

const streams: FakeStream[] = [];
beforeEach(() => {
  streams.length = 0;
  resetNetworkBff();
  server.use(...networkBffHandlers);
  vi.stubGlobal(
    'EventSource',
    class {
      constructor(public url: string) {
        const stream = new FakeStream();
        Object.assign(stream, { url });
        streams.push(stream);
        return stream as unknown as EventSource;
      }
    },
  );
});
afterEach(() => vi.unstubAllGlobals());

const view = () => render(<NetworkBoardView ownHref="/advisor/board" />);
const board = (entries: unknown[]) => HttpResponse.json(parseBoard({ ...BOARD_BODY, entries, generated_at: new Date().toISOString() }, 'backend'));

describe('NetworkBoardView', () => {
  it('shows the heading, the scope and a tile for each service, with the service lines', async () => {
    const { container } = view();
    expect(await screen.findByRole('heading', { level: 1, name: 'Sample Network capacity' })).toBeInTheDocument();
    expect(container.querySelectorAll('[data-el="NET-BOARD-TILE"]')).toHaveLength(4);
    expect(screen.getByRole('link', { name: 'Phone UCR West on 01632 960010' })).toBeInTheDocument();
    expect(screen.getByText('Showing: Network, Sample Network')).toBeInTheDocument();
    expect(screen.getByText('Your organisation')).toBeInTheDocument();
  });

  it('reads the board and the service lines of the network it was offered, by the one networkId key', async () => {
    view();
    await screen.findByRole('heading', { level: 1 });
    await waitFor(() => expect(seenNetworkBff.map((c) => c.path)).toContain('/api/bff/network/phones'));
    const asked = seenNetworkBff.filter((c) => c.path !== '/api/bff/network');
    expect(asked.length).toBeGreaterThan(0);
    for (const call of asked) expect(call.query).toBe('networkId=net-sample');
  });

  it('opens the stream of the network, by the same key', async () => {
    view();
    await screen.findByRole('heading', { level: 1 });
    await waitFor(() => expect(streams).toHaveLength(1));
    expect((streams[0] as unknown as { url: string }).url).toBe('/api/bff/network/events?networkId=net-sample');
  });

  it('is the "not available" panel, with no figure, when the board is refused', async () => {
    server.use(http.get('/api/bff/network/board', () => HttpResponse.json({ code: 'not-found' }, { status: 404 })));
    const { container } = view();
    expect(await screen.findByText('Network view not available')).toBeInTheDocument();
    expect(container.querySelectorAll('[data-el="NET-BOARD-TILE"]')).toHaveLength(0);
    expect(screen.queryByText('UCR West')).toBeNull();
  });

  it('removes every figure when the network ends the viewer’s scope while the page is open', async () => {
    const { container } = view();
    await screen.findByRole('heading', { level: 1 });
    await waitFor(() => expect(streams).toHaveLength(1));
    server.use(http.get('/api/bff/network/board', () => HttpResponse.json({ code: 'not-found' }, { status: 404 })));
    await act(async () => streams[0]!.emit('scope-ended', '{}'));
    expect(await screen.findByText('Network view not available')).toBeInTheDocument();
    expect(container.querySelectorAll('[data-el="NET-BOARD-TILE"]')).toHaveLength(0);
  });

  it('keeps the figures on screen when a read fails while the stream has only just dropped', async () => {
    const { container } = view();
    await screen.findByRole('heading', { level: 1 });
    await waitFor(() => expect(streams).toHaveLength(1));
    server.use(http.get('/api/bff/network/board', () => HttpResponse.json({ code: 'exception' }, { status: 503 })));
    await act(async () => streams[0]!.fail());
    await act(async () => streams[0]!.emit('network-board', '{"changedAt":"2026-10-23T13:12:00+00:00"}'));
    // One failed read with the stream not yet long down is still current; the stream being down for
    // longer than the gap makes it last known (the same rule as the wall).
    expect(container.querySelectorAll('[data-el="NET-BOARD-TILE"]')).toHaveLength(4);
  });

  it('says an organisation stopped sharing when its services leave the board, with the date from the history', async () => {
    view();
    await screen.findByRole('heading', { level: 1 });
    await waitFor(() => expect(streams).toHaveLength(1));
    server.use(
      http.get('/api/bff/network/board', () => board(BOARD_BODY.entries.filter((e) => e.organisation_name !== 'Sample Area D'))),
      http.get('/api/bff/network/directory', () =>
        HttpResponse.json({
          entries: [],
          systemName: 'x',
          pathwayName: 'y',
          timeZone: 'Europe/London',
        }),
      ),
    );
    await act(async () => streams[0]!.emit('network-board', '{"changedAt":"2026-10-23T13:12:00+00:00"}'));
    expect(await screen.findByText('No longer shown: Sample Area D.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'See history' })).toHaveAttribute('href', '/network/history');
  });

  it('says nothing is shared yet for a network with no services', async () => {
    server.use(http.get('/api/bff/network/board', () => board([])));
    view();
    expect(await screen.findByText('No services are shared yet')).toBeInTheDocument();
  });

  it('shows the board even when the service lines cannot be read, and says so', async () => {
    server.use(http.get('/api/bff/network/phones', () => HttpResponse.json({ code: 'exception' }, { status: 503 })));
    view();
    expect(await screen.findByText('Service line numbers could not be loaded. Phone to confirm.')).toBeInTheDocument();
    expect(screen.getAllByRole('heading', { level: 2 }).length).toBeGreaterThan(0);
    expect(within(document.body).queryByText('No number shared')).toBeNull();
  });

  it('shows a board entry with the fields it gets and nothing else', async () => {
    server.use(http.get('/api/bff/network/board', () => board([boardEntry({ service_name: 'Only service' })])));
    const { container } = view();
    expect(await screen.findByText('Only service')).toBeInTheDocument();
    expect(container.innerHTML).not.toMatch(/trust-|tenant|net-sample/i);
  });
});
