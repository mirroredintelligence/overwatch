import { act, render, screen, within } from '@testing-library/react';
import { renderToString } from 'react-dom/server';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BoardFetchError, type FetchedBoard } from '@/lib/board/client';
import { runAxe } from '@/test/a11y';
import { FakeStream } from '@/test/fakeStream';
import { BOARD_A, BOARD_SURGE, boardBuiltAt, GENERATED_AT, MAIN_ENTRIES } from '@/test/fixtures/board';
import { server } from '@/test/msw/server';
import { LiveBoard } from './LiveBoard';

const replace = vi.hoisted(() => vi.fn());
vi.mock('next/navigation', () => ({ useRouter: () => ({ replace }) }));

const T0 = Date.parse(GENERATED_AT);
const iso = (ms: number) => new Date(ms).toISOString();

beforeEach(() => {
  replace.mockClear();
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] });
  vi.setSystemTime(T0);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function builtNow(over: Partial<typeof BOARD_A> = {}): FetchedBoard {
  return { board: { ...boardBuiltAt(BOARD_A, iso(Date.now())), ...over }, serverTime: Date.now() };
}

function mount(props: Partial<Parameters<typeof LiveBoard>[0]> = {}) {
  const stream = new FakeStream();
  const fetchBoard = vi.fn<(signal: AbortSignal) => Promise<FetchedBoard>>(async () => builtNow());
  const onUnpaired = vi.fn();
  const view = render(
    <LiveBoard
      initialBoard={BOARD_A}
      serverTime={T0}
      fetchBoard={fetchBoard}
      createEventSource={() => stream}
      onUnpaired={onUnpaired}
      {...props}
    />,
  );
  return { ...view, stream, fetchBoard, onUnpaired };
}

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

function tiles(container: HTMLElement) {
  return Array.from(container.querySelectorAll<HTMLElement>('[data-el="WALL-TILE"]'));
}

async function goOffline(m: ReturnType<typeof mount>) {
  await act(async () => m.stream.open());
  await advance(0);
  m.fetchBoard.mockRejectedValue(new BoardFetchError('unreachable', 503));
  await act(async () => m.stream.fail());
  await advance(61_000);
}

describe('LiveBoard: the tenant’s own line (TEN-049)', () => {
  it('passes the line the page read from the profile on to the board, and has none of its own', () => {
    const { rerender } = render(<LiveBoard initialBoard={BOARD_A} serverTime={Date.parse(GENERATED_AT)} subtitle="Access team A" createEventSource={() => null} />);
    expect(screen.getByText('Access team A')).toBeInTheDocument();
    rerender(<LiveBoard initialBoard={BOARD_A} serverTime={Date.parse(GENERATED_AT)} createEventSource={() => null} />);
    expect(screen.queryByText('Access team A')).toBeNull();
    expect(document.body.textContent).not.toMatch(/single point of access/i);
  });
});

describe('LiveBoard: online', () => {
  it('shows the board it was given, as current, with no banner and nothing announced', () => {
    const { container } = mount();

    expect(screen.getByRole('heading', { level: 1, name: 'Dorset urgent care capacity' })).toBeInTheDocument();
    expect(tiles(container)).toHaveLength(MAIN_ENTRIES.length);
    expect(tiles(container)[0]).toHaveAttribute('data-status', 'accepting');
    // Nothing is said: the only live region is the one for status changes (KI-56), and it is empty.
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(Array.from(container.querySelectorAll('[role="status"], [aria-live]')).map((e) => e.textContent)).toEqual(['']);
    expect(container.textContent).not.toContain('Last known');
  });

  it('applies a refreshed board in place, whole, with no announcement', async () => {
    const m = mount();
    await act(async () => m.stream.open());
    await advance(0);
    const next = builtNow({ organisation: 'Refreshed area' });
    next.board.entries = [{ ...MAIN_ENTRIES[0], effectiveAvailable: 7, used: 1, name: 'UCR West' }];
    m.fetchBoard.mockResolvedValueOnce(next);

    await act(async () => m.stream.emit('board'));
    await advance(0);

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Refreshed area urgent care capacity');
    expect(tiles(m.container)).toHaveLength(1);
    expect(within(tiles(m.container)[0]).getByText('7')).toBeInTheDocument();
    // A refresh that changes a figure and no status says nothing (KI-56): the live region stays empty.
    expect(m.container.querySelector('[role="alert"]')).toBeNull();
    expect(Array.from(m.container.querySelectorAll('[role="status"], [aria-live]')).map((e) => e.textContent)).toEqual(['']);
  });

  it('shows a note in words, and no alert, when the stream is down but the poll still works', async () => {
    const m = mount();
    await act(async () => m.stream.open());
    await act(async () => m.stream.fail());
    await advance(61_000);

    expect(m.container.querySelector('[data-el="WALL-STREAM-NOTE"]')).toHaveTextContent('Live updates paused');
    expect(screen.queryByRole('alert')).toBeNull();
    expect(tiles(m.container)[0]).toHaveAttribute('data-status', 'accepting');
  });

  it('has no axe violations', async () => {
    const { container } = mount();

    expect(tiles(container)).toHaveLength(MAIN_ENTRIES.length);
    vi.useRealTimers(); // axe uses timers of its own
    expect(await runAxe(container)).toHaveNoViolations();
  });
});

describe('LiveBoard: the first paint on the server', () => {
  it('already says Last known in the HTML the server sends for a board that is old when served', () => {
    const html = renderToString(
      <LiveBoard initialBoard={boardBuiltAt(BOARD_A, iso(T0 - 20 * 60_000))} serverTime={T0} />,
    );

    expect(html).toContain('Tool offline since');
    expect(html).toContain('Do not rely on this. Phone to confirm.');
    expect(html).not.toMatch(/Updated \d+ min ago/);
  });

  it('sends a current board as current', () => {
    const html = renderToString(<LiveBoard initialBoard={BOARD_A} serverTime={T0} />);

    expect(html).not.toContain('Tool offline since');
    expect(html).not.toContain('Last known');
  });
});

describe('LiveBoard: offline', () => {
  it('shows the banner as an alert with the offline time, once the stream is down for 10 s and the refetch fails', async () => {
    const m = mount();

    await goOffline(m);

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('Tool offline since 14:13');
    expect(alert).toHaveTextContent('Figures are the last known and may be wrong. Use the whiteboard and phone process.');
  });

  it('turns every tile into Last known, keeps the numbers, and ages them from the time now', async () => {
    const m = mount();

    await goOffline(m);

    const all = tiles(m.container);
    expect(all).toHaveLength(MAIN_ENTRIES.length);
    for (const t of all) {
      expect(t).toHaveAttribute('data-status', 'last-known');
      expect(within(t).getByText('Last known')).toBeInTheDocument();
      expect(within(t).getByText('Do not rely on this. Phone to confirm.')).toBeInTheDocument();
    }
    expect(within(all[0]).getByText('4')).toBeInTheDocument();
    expect(all[0].textContent).toContain('Last known 14:03');
    expect(all[0].textContent).toContain('10 min ago');
    expect(m.container.textContent).not.toMatch(/Updated \d+ min ago/);
  });

  it('announces nothing again as time passes: the same single alert, with the same text', async () => {
    const m = mount();
    await goOffline(m);
    const alert = screen.getByRole('alert');
    const text = alert.textContent;

    await advance(5 * 60_000);

    expect(screen.getAllByRole('alert')).toHaveLength(1);
    expect(screen.getByRole('alert')).toBe(alert);
    expect(screen.getByRole('alert').textContent).toBe(text);
    // The one live region of the page is the status announcer, and offline it says nothing (KI-56).
    expect(Array.from(m.container.querySelectorAll('[aria-live], [role="status"]')).map((e) => e.textContent)).toEqual(['']);
  });

  it('lets the ages grow while offline, minute by minute', async () => {
    const m = mount();
    await goOffline(m);
    expect(tiles(m.container)[0].textContent).toContain('10 min ago');

    await advance(5 * 60_000);

    expect(tiles(m.container)[0].textContent).toContain('15 min ago');
    expect(screen.getByText(/Board last refreshed 14:12/)).toHaveTextContent('Board last refreshed 14:12 · 6 min ago');
  });

  it('recovers when one refetch succeeds: the banner goes and the tiles are current again', async () => {
    const m = mount();
    await goOffline(m);
    m.fetchBoard.mockReset();
    m.fetchBoard.mockImplementation(async () => builtNow());

    await advance(60_000);

    expect(screen.queryByRole('alert')).toBeNull();
    expect(tiles(m.container)[0]).toHaveAttribute('data-status', 'accepting');
    expect(m.container.textContent).not.toContain('Last known');
  });

  it('is Last known when the page is served with a board that is already old', () => {
    const { container } = mount({ initialBoard: boardBuiltAt(BOARD_A, iso(T0 - 20 * 60_000)) });

    expect(screen.getByRole('alert')).toHaveTextContent('Tool offline since');
    for (const t of tiles(container)) expect(t).toHaveAttribute('data-status', 'last-known');
  });

  it('is Last known after 3 minutes with the stream open and the refetches failing', async () => {
    const m = mount();
    await act(async () => m.stream.open());
    await advance(0);
    m.fetchBoard.mockRejectedValue(new BoardFetchError('unreachable', 503));

    await advance(181_000);

    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(tiles(m.container)[0]).toHaveAttribute('data-status', 'last-known');
  });

  it('has no axe violations while Last known', async () => {
    const m = mount();
    await goOffline(m);

    expect(screen.getByRole('alert')).toBeInTheDocument();
    vi.useRealTimers(); // axe uses timers of its own
    expect(await runAxe(m.container)).toHaveNoViolations();
  });
});

describe('LiveBoard: the pressure banner follows the board (W07)', () => {
  const surgeNow = (): FetchedBoard => ({ board: boardBuiltAt(BOARD_SURGE, iso(Date.now())), serverTime: Date.now() });

  it('appears when a refetch says the system is under pressure and goes when it says it is not', async () => {
    const m = mount();
    await act(async () => m.stream.open());
    await advance(0);
    expect(screen.queryByText('System under pressure')).toBeNull();

    m.fetchBoard.mockResolvedValueOnce(surgeNow());
    await act(async () => m.stream.emit('board'));
    await advance(0);
    expect(screen.getByText('System under pressure')).toBeInTheDocument();
    expect(screen.getByText('All 9 services are limited, not accepting or over capacity.')).toBeInTheDocument();

    m.fetchBoard.mockResolvedValueOnce(builtNow());
    await act(async () => m.stream.emit('board'));
    await advance(0);
    expect(screen.queryByText('System under pressure')).toBeNull();
  });

  it('is replaced by the Last known banner, never shown beside it, when the board goes offline', async () => {
    const m = mount({ initialBoard: BOARD_SURGE });
    expect(screen.getByText('System under pressure')).toBeInTheDocument();

    await goOffline(m);

    expect(screen.queryByText('System under pressure')).toBeNull();
    expect(screen.getAllByRole('alert')).toHaveLength(1);
    expect(screen.getByRole('alert')).toHaveTextContent('Tool offline since');
    for (const t of tiles(m.container)) {
      expect(t).toHaveAttribute('data-status', 'last-known');
      // The key under the grid names every status, so look at the tiles only.
      expect(t.textContent).not.toMatch(/pending|Over capacity/);
    }
  });

  it('comes back with the board when the board recovers', async () => {
    const m = mount({ initialBoard: BOARD_SURGE });
    await goOffline(m);
    m.fetchBoard.mockReset();
    m.fetchBoard.mockImplementation(async () => surgeNow());

    await advance(60_000);

    expect(screen.getByText('System under pressure')).toBeInTheDocument();
    expect(m.container.textContent).not.toContain('Last known');
  });
});

describe('LiveBoard: an update that fails to parse', () => {
  it('falls back to Last known with the old figures, never to a blank board or a wrong tile', async () => {
    const m = mount({ fetchBoard: undefined });
    server.use(
      http.get('*/api/bff/board', () =>
        HttpResponse.json({ ...BOARD_A, entries: [{ ...BOARD_A.entries[0], status: 'busy', used: -3 }] }),
      ),
    );

    await advance(60_000);

    expect(screen.getByRole('alert')).toHaveTextContent('Tool offline since');
    expect(tiles(m.container)).toHaveLength(MAIN_ENTRIES.length);
    expect(tiles(m.container)[0]).toHaveAttribute('data-status', 'last-known');
    expect(within(tiles(m.container)[0]).getByText('4')).toBeInTheDocument();
    expect(m.container.textContent).not.toContain('-3');
  });

  it.each([
    ['a body that is not JSON', () => new HttpResponse('<html>bad gateway</html>', { headers: { 'Content-Type': 'text/html' } })],
    ['an empty object', () => HttpResponse.json({})],
    ['a negative count', () => HttpResponse.json({ ...BOARD_A, entries: [{ ...BOARD_A.entries[0], established: -1 }] })],
    ['a fractional count', () => HttpResponse.json({ ...BOARD_A, entries: [{ ...BOARD_A.entries[0], used: 2.5 }] })],
  ])('treats %s as Last known', async (_label, answer) => {
    const m = mount({ fetchBoard: undefined });
    server.use(http.get('*/api/bff/board', answer));

    await advance(60_000);

    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(tiles(m.container)).toHaveLength(MAIN_ENTRIES.length);
  });
});

describe('LiveBoard: through the BFF, as the paired screen (no tenant from anywhere)', () => {
  it('opens the stream at /api/bff/events with no query string, and reads /api/bff/board with no query or tenant header', async () => {
    const urls: string[] = [];
    class RecordingSource extends FakeStream {
      constructor(url: string | URL) {
        super();
        urls.push(String(url));
      }
    }
    vi.stubGlobal('EventSource', RecordingSource);
    const seen: Request[] = [];
    server.use(
      http.get('*/api/bff/board', ({ request }) => {
        seen.push(request.clone());
        return HttpResponse.json(boardBuiltAt(BOARD_A, iso(Date.now())));
      }),
    );
    mount({ createEventSource: undefined, fetchBoard: undefined });

    await advance(60_000);

    expect(urls).toEqual(['/api/bff/events']);
    expect(seen.length).toBeGreaterThan(0);
    for (const request of seen) {
      expect(new URL(request.url).search).toBe('');
      for (const name of request.headers.keys()) expect(name).not.toMatch(/tenant|organi[sz]ation|authorization/i);
    }
  });

  it('goes to /screen/pair when the BFF refuses the screen with 401', async () => {
    server.use(http.get('*/api/bff/board', () => HttpResponse.json({ code: 'no-session' }, { status: 401 })));
    mount({ fetchBoard: undefined, onUnpaired: undefined });

    await advance(60_000);

    expect(replace).toHaveBeenCalledTimes(1);
    expect(replace).toHaveBeenCalledWith('/screen/pair');
  });
});

describe('LiveBoard: clean-up', () => {
  it('closes the stream and clears every timer on unmount', async () => {
    const m = mount();
    await act(async () => m.stream.open());
    await advance(0);

    m.unmount();

    expect(m.stream.closed).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });
});
