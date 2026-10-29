import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FakeStream } from '@/test/fakeStream';
import { BOARD_A, BOARD_B, boardBuiltAt, entry, GENERATED_AT } from '@/test/fixtures/board';
import { BoardFetchError, type FetchedBoard } from './client';
import { STALE_AFTER_MS } from './liveness';
import type { Board } from './types';
import { useBoardFeed, type BoardFeedOptions } from './useBoardFeed';

// Time-driven tests (fake timers). The clock starts at the sample board's own
// time, so the first board is fresh. "Server time" is the same clock unless a
// test moves it.

const T0 = Date.parse(GENERATED_AT);
const iso = (ms: number) => new Date(ms).toISOString();

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(T0);
});

afterEach(() => {
  vi.useRealTimers();
});

function builtNow(): FetchedBoard {
  return { board: boardBuiltAt(BOARD_A, iso(Date.now())), serverTime: Date.now() };
}

function mount(over: Partial<BoardFeedOptions> = {}) {
  const fetchBoard = vi.fn<(signal: AbortSignal) => Promise<FetchedBoard>>(async () => builtNow());
  const streams: FakeStream[] = [];
  const createEventSource = vi.fn(() => {
    const stream = new FakeStream();
    streams.push(stream);
    return stream;
  });
  const onUnpaired = vi.fn();
  const options: BoardFeedOptions = {
    initialBoard: BOARD_A,
    serverTime: T0,
    fetchBoard,
    createEventSource,
    onUnpaired,
    ...over,
  };
  const hook = renderHook(() => useBoardFeed(options));
  return { ...hook, fetchBoard, createEventSource, streams, onUnpaired, stream: () => streams[streams.length - 1] };
}

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

async function settle() {
  await advance(0);
}

async function openStream(stream: FakeStream) {
  await act(async () => {
    stream.open();
  });
  await settle();
}

async function emit(stream: FakeStream, type = 'board') {
  await act(async () => {
    stream.emit(type);
  });
  await settle();
}

async function breakStream(stream: FakeStream, gaveUp = false) {
  await act(async () => {
    stream.fail(gaveUp);
  });
}

const unreachable = () => new BoardFetchError('unreachable', 503);
const unreadable = () => new BoardFetchError('unreadable', 502);

describe('useBoardFeed: refetching', () => {
  it('opens the stream as the paired session, with no URL of its own to choose (the factory decides)', () => {
    const { createEventSource } = mount();
    expect(createEventSource).toHaveBeenCalledTimes(1);
  });

  it('a board event triggers exactly one refetch', async () => {
    const { stream, fetchBoard } = mount();
    await openStream(stream());
    fetchBoard.mockClear();

    await emit(stream(), 'board');

    expect(fetchBoard).toHaveBeenCalledTimes(1);
  });

  it('listens for the back end event name (board) and for board.updated, and refetches on each', async () => {
    const { stream, fetchBoard } = mount();
    await openStream(stream());
    expect(stream().listenerNames()).toEqual(expect.arrayContaining(['board', 'board.updated']));
    fetchBoard.mockClear();

    await emit(stream(), 'board.updated');

    expect(fetchBoard).toHaveBeenCalledTimes(1);
  });

  it('does not refetch for a booking event or an event it does not know (the wall shows capacity only)', async () => {
    const { stream, fetchBoard } = mount();
    await openStream(stream());
    fetchBoard.mockClear();

    await emit(stream(), 'booking.updated');
    await emit(stream(), 'something.else');

    expect(fetchBoard).not.toHaveBeenCalled();
  });

  it('refetches the whole board when the stream first opens, so nothing between page load and stream is missed', async () => {
    const { stream, fetchBoard } = mount();

    await openStream(stream());

    expect(fetchBoard).toHaveBeenCalledTimes(1);
  });

  it('after 60 s with no events it refetches, and then every 60 s', async () => {
    const { fetchBoard, stream } = mount();
    await openStream(stream());
    fetchBoard.mockClear();

    await advance(59_999);
    expect(fetchBoard).not.toHaveBeenCalled();
    await advance(1);
    expect(fetchBoard).toHaveBeenCalledTimes(1);
    await advance(120_000);
    expect(fetchBoard).toHaveBeenCalledTimes(3);
  });

  it('turns a burst of events into one refetch now and at most one more, never one request per event', async () => {
    const { stream, fetchBoard } = mount();
    await openStream(stream());
    fetchBoard.mockClear();
    let release: (value: FetchedBoard) => void = () => undefined;
    fetchBoard.mockImplementationOnce(() => new Promise<FetchedBoard>((resolve) => (release = resolve)));

    await emit(stream());
    await emit(stream());
    await emit(stream());
    expect(fetchBoard).toHaveBeenCalledTimes(1);

    await act(async () => release(builtNow()));
    await settle();
    expect(fetchBoard).toHaveBeenCalledTimes(2);
    await advance(1_000);
    expect(fetchBoard).toHaveBeenCalledTimes(2);
  });

  it('shows the board it was given at first, then the one it fetched', async () => {
    const { result, stream, fetchBoard } = mount();
    expect(result.current.board).toBe(BOARD_A);
    const next = boardBuiltAt(BOARD_B, iso(T0 + 5_000));
    fetchBoard.mockResolvedValueOnce({ board: next, serverTime: T0 + 5_000 });

    await advance(5_000);
    await openStream(stream());

    expect(result.current.board).toBe(next);
  });

  it('does not restart the stream or the timers when it re-renders with new function identities', async () => {
    const fetchBoard = vi.fn(async (signal: AbortSignal) => {
      void signal;
      return builtNow();
    });
    const created: FakeStream[] = [];
    const { rerender } = renderHook(() =>
      useBoardFeed({
        initialBoard: BOARD_A,
        serverTime: T0,
        fetchBoard: (signal) => fetchBoard(signal),
        createEventSource: () => {
          const s = new FakeStream();
          created.push(s);
          return s;
        },
        onUnpaired: () => undefined,
      }),
    );

    rerender();
    rerender();
    await settle();

    expect(created).toHaveLength(1);
    expect(vi.getTimerCount()).toBeLessThanOrEqual(3);
  });
});

describe('useBoardFeed: replacing the board', () => {
  it('replaces the whole board with the new one, the very object, never merging', async () => {
    const { result, stream, fetchBoard } = mount();
    await openStream(stream());
    const next: Board = {
      ...boardBuiltAt(BOARD_A, iso(Date.now())),
      entries: [entry({ serviceId: 'svc-new', name: 'Only service' })],
      organisation: 'Replaced',
    };
    fetchBoard.mockResolvedValueOnce({ board: next, serverTime: Date.now() });

    await emit(stream());

    expect(result.current.board).toBe(next);
    expect(result.current.board.entries.map((e) => e.serviceId)).toEqual(['svc-new']);
  });

  it('after a stream gap and reconnect, refetches and replaces the whole board', async () => {
    const { result, stream, fetchBoard } = mount();
    await openStream(stream());
    await breakStream(stream());
    await advance(20_000);
    fetchBoard.mockClear();
    const after: Board = { ...boardBuiltAt(BOARD_B, iso(Date.now() + 1_000)), organisation: 'After the gap' };
    fetchBoard.mockResolvedValueOnce({ board: after, serverTime: Date.now() });

    await openStream(stream());

    expect(fetchBoard).toHaveBeenCalledTimes(1);
    expect(result.current.board).toBe(after);
    expect(result.current.assessment).toEqual({ mode: 'live', streamPaused: false });
  });

  it('does not let an older board replace a newer one (out of order)', async () => {
    const { result, stream, fetchBoard } = mount();
    await openStream(stream());
    const newer = boardBuiltAt(BOARD_A, iso(T0 + 20_000));
    const older = boardBuiltAt(BOARD_B, iso(T0 + 10_000));
    await advance(20_000);
    fetchBoard.mockResolvedValueOnce({ board: newer, serverTime: Date.now() });
    await emit(stream());
    expect(result.current.board).toBe(newer);

    fetchBoard.mockResolvedValueOnce({ board: older, serverTime: Date.now() });
    await emit(stream());

    expect(result.current.board).toBe(newer);
    expect(result.current.board.organisation).toBe('Dorset');
  });

  it('accepts a board with the same time as the one it holds', async () => {
    const { result, stream, fetchBoard } = mount();
    await openStream(stream());
    const same = { ...boardBuiltAt(BOARD_A, iso(Date.now())), organisation: 'Same time' };
    fetchBoard.mockResolvedValueOnce({ board: same, serverTime: Date.now() });
    await emit(stream());
    const again = { ...same, organisation: 'Same time again' };
    fetchBoard.mockResolvedValueOnce({ board: again, serverTime: Date.now() });

    await emit(stream());

    expect(result.current.board).toBe(again);
  });

  it('keeps the newer board when a slow older answer arrives after it', async () => {
    const { result, stream, fetchBoard } = mount();
    await openStream(stream());
    fetchBoard.mockClear();
    let releaseSlow: (value: FetchedBoard) => void = () => undefined;
    fetchBoard.mockImplementationOnce(() => new Promise<FetchedBoard>((resolve) => (releaseSlow = resolve)));
    await emit(stream());
    const slow = boardBuiltAt(BOARD_B, iso(T0 - 30_000));
    const fresh = boardBuiltAt(BOARD_A, iso(T0 + 30_000));
    fetchBoard.mockResolvedValueOnce({ board: fresh, serverTime: T0 + 30_000 });
    await emit(stream());

    await act(async () => releaseSlow({ board: slow, serverTime: Date.now() }));
    await settle();

    expect(result.current.board).toBe(fresh);
  });

  it('refuses a board built in the future, keeps the last good board, and is not pinned by it afterwards', async () => {
    const { result, stream, fetchBoard } = mount();
    await openStream(stream());
    const future = boardBuiltAt(BOARD_B, iso(Date.now() + 10 * 60_000));
    fetchBoard.mockResolvedValueOnce({ board: future, serverTime: Date.now() });

    await emit(stream());

    expect(result.current.board.organisation).toBe('Dorset');
    expect(result.current.assessment).toMatchObject({ mode: 'last-known', reason: 'unreadable' });

    const good = { ...boardBuiltAt(BOARD_A, iso(Date.now())), organisation: 'Good again' };
    fetchBoard.mockResolvedValueOnce({ board: good, serverTime: Date.now() });
    await emit(stream());
    expect(result.current.board).toBe(good);
    expect(result.current.assessment).toEqual({ mode: 'live', streamPaused: false });
  });
});

describe('useBoardFeed: going offline and recovering', () => {
  it('stream down for 11 s and the next refetch fails: offline, since the time of the first failure', async () => {
    const { result, stream, fetchBoard } = mount();
    await openStream(stream());
    await breakStream(stream());
    fetchBoard.mockRejectedValue(unreachable());

    await advance(60_000);

    expect(result.current.assessment).toMatchObject({
      mode: 'last-known',
      reason: 'offline',
      since: iso(T0 + 60_000),
    });
  });

  it('a refetch that failed before the stream gap is the offline time, and the page goes offline when the gap passes 10 s', async () => {
    const { result, stream, fetchBoard } = mount();
    await openStream(stream());
    fetchBoard.mockRejectedValue(unreachable());
    await advance(1_000);
    await emit(stream());
    expect(result.current.assessment.mode).toBe('live');
    await breakStream(stream());

    await advance(10_000);
    expect(result.current.assessment).toMatchObject({ mode: 'live', streamPaused: false });
    await advance(1_001);

    expect(result.current.assessment).toMatchObject({ mode: 'last-known', reason: 'offline', since: iso(T0 + 1_000) });
  });

  it('stream down for 11 s but the refetch succeeds: not offline, only paused', async () => {
    const { result, stream } = mount();
    await openStream(stream());
    await breakStream(stream());

    await advance(61_000);

    expect(result.current.assessment).toEqual({ mode: 'live', streamPaused: true });
  });

  it('is not paused during the first 10 s of a stream gap', async () => {
    const { result, stream } = mount();
    await openStream(stream());
    await breakStream(stream());

    await advance(9_000);

    expect(result.current.assessment).toEqual({ mode: 'live', streamPaused: false });
  });

  it('from offline, one successful refetch brings it back online with the new board', async () => {
    const { result, stream, fetchBoard } = mount();
    await openStream(stream());
    await breakStream(stream());
    fetchBoard.mockRejectedValue(unreachable());
    await advance(60_000);
    expect(result.current.assessment.mode).toBe('last-known');
    const recovered = { ...boardBuiltAt(BOARD_A, iso(Date.now() + 60_000)), organisation: 'Recovered' };
    fetchBoard.mockReset();
    fetchBoard.mockResolvedValue({ board: recovered, serverTime: Date.now() + 60_000 });

    await advance(60_000);

    expect(result.current.assessment).toEqual({ mode: 'live', streamPaused: true });
    expect(result.current.board).toBe(recovered);
  });

  it('a refetch that succeeds with an old board does not bring it back online', async () => {
    const { result, stream, fetchBoard } = mount();
    await openStream(stream());
    await breakStream(stream());
    fetchBoard.mockRejectedValue(unreachable());
    await advance(5 * 60_000);
    expect(result.current.assessment).toMatchObject({ mode: 'last-known' });
    const held = result.current.board;
    fetchBoard.mockReset();
    fetchBoard.mockResolvedValue({ board: boardBuiltAt(BOARD_B, iso(T0 - 600_000)), serverTime: Date.now() });

    await advance(60_000);

    expect(result.current.assessment).toMatchObject({ mode: 'last-known', reason: 'old' });
    expect(result.current.board).toBe(held);
  });

  it('the board stays what it was when offline: the last good board, never blank', async () => {
    const { result, stream, fetchBoard } = mount();
    await openStream(stream());
    await breakStream(stream());
    fetchBoard.mockRejectedValue(unreachable());

    await advance(5 * 60_000);

    expect(result.current.assessment.mode).toBe('last-known');
    expect(result.current.board.entries.length).toBeGreaterThan(0);
    expect(result.current.board.generatedAt).toBe(iso(T0));
  });
});

describe('useBoardFeed: an answer it cannot read', () => {
  it('goes to Last known at once, with the stream up, and keeps the last good board', async () => {
    const { result, stream, fetchBoard } = mount();
    await openStream(stream());
    const held = result.current.board;
    fetchBoard.mockRejectedValueOnce(unreadable());

    await emit(stream());

    expect(result.current.assessment).toMatchObject({ mode: 'last-known', reason: 'unreadable', since: iso(T0) });
    expect(result.current.board).toBe(held);
  });

  it('comes back with the next board it can read', async () => {
    const { result, stream, fetchBoard } = mount();
    await openStream(stream());
    fetchBoard.mockRejectedValueOnce(unreadable());
    await emit(stream());
    const good = boardBuiltAt(BOARD_A, iso(Date.now() + 1_000));
    fetchBoard.mockResolvedValueOnce({ board: good, serverTime: Date.now() + 1_000 });

    await emit(stream());

    expect(result.current.assessment).toEqual({ mode: 'live', streamPaused: false });
    expect(result.current.board).toBe(good);
  });

  it('treats an unexpected throw from the fetch as a failure, not a crash', async () => {
    const { result, stream, fetchBoard } = mount();
    await openStream(stream());
    const held = result.current.board;
    fetchBoard.mockRejectedValue(new TypeError('boom'));
    await breakStream(stream());

    await advance(61_000);

    expect(result.current.assessment).toMatchObject({ mode: 'last-known', reason: 'offline' });
    expect(result.current.board).toBe(held);
  });
});

describe('useBoardFeed: a board that stops refreshing', () => {
  it('is Last known after 3 minutes even though the stream says it is open and every poll fails', async () => {
    const { result, stream, fetchBoard } = mount();
    await openStream(stream());
    fetchBoard.mockRejectedValue(unreachable());

    await advance(STALE_AFTER_MS - 1_000);
    expect(result.current.assessment.mode).toBe('live');
    await advance(2_000);

    expect(result.current.assessment).toMatchObject({ mode: 'last-known', reason: 'old', since: iso(T0 + 60_000) });
  });

  it('is Last known after 3 minutes when the back end keeps answering with the same old board', async () => {
    const { result, stream, fetchBoard } = mount();
    await openStream(stream());
    fetchBoard.mockImplementation(async () => ({ board: BOARD_A, serverTime: Date.now() }));

    await advance(STALE_AFTER_MS + 1_000);

    expect(result.current.assessment).toMatchObject({ mode: 'last-known', reason: 'old', since: iso(T0) });
  });

  it('is Last known when a request hangs forever, and abandons it so the next poll can run', async () => {
    const { result, stream, fetchBoard } = mount();
    await openStream(stream());
    fetchBoard.mockClear();
    const signals: AbortSignal[] = [];
    fetchBoard.mockImplementation((signal) => {
      signals.push(signal);
      return new Promise<FetchedBoard>(() => undefined);
    });

    await advance(60_000);
    expect(fetchBoard).toHaveBeenCalledTimes(1);
    expect(signals[0].aborted).toBe(false);
    await advance(20_000);
    expect(signals[0].aborted).toBe(true);
    await advance(40_000);
    expect(fetchBoard).toHaveBeenCalledTimes(2);
    await advance(STALE_AFTER_MS);

    expect(result.current.assessment).toMatchObject({ mode: 'last-known' });
  });

  it('notices the board is old on the next tick after the machine slept (the clock jumped)', async () => {
    const { result, stream } = mount();
    await openStream(stream());

    act(() => {
      vi.setSystemTime(T0 + 3_600_000);
    });
    await advance(1_000);

    expect(result.current.assessment).toMatchObject({ mode: 'last-known', reason: 'old' });
  });

  it('measures the age on the back end clock, not the browser clock', async () => {
    const hourAhead = 3_600_000;
    const { result, stream, fetchBoard } = mount({
      serverTime: T0 + hourAhead,
      initialBoard: boardBuiltAt(BOARD_A, iso(T0 + hourAhead)),
    });
    fetchBoard.mockImplementation(async () => ({
      board: boardBuiltAt(BOARD_A, iso(Date.now() + hourAhead)),
      serverTime: Date.now() + hourAhead,
    }));
    await openStream(stream());

    await advance(61_000);
    expect(result.current.assessment).toEqual({ mode: 'live', streamPaused: false });

    fetchBoard.mockRejectedValue(unreachable());
    await advance(STALE_AFTER_MS + 61_000);
    expect(result.current.assessment).toMatchObject({ mode: 'last-known' });
  });
});

describe('useBoardFeed: the back end clock from each answer', () => {
  it('takes the offset from the answer, not only from the page: a board built on a server clock an hour ahead is live', async () => {
    const hourAhead = 3_600_000;
    const { result, stream, fetchBoard } = mount();
    fetchBoard.mockImplementation(async () => ({
      board: boardBuiltAt(BOARD_A, iso(Date.now() + hourAhead)),
      serverTime: Date.now() + hourAhead,
    }));

    await openStream(stream());

    expect(result.current.assessment).toEqual({ mode: 'live', streamPaused: false });
    await advance(61_000);
    expect(result.current.assessment).toEqual({ mode: 'live', streamPaused: false });
  });
});

describe('useBoardFeed: first render', () => {
  it('is live for a fresh board on the very first render, with no effect having run', () => {
    const { result } = mount();
    expect(result.current.assessment).toEqual({ mode: 'live', streamPaused: false });
  });

  it('is Last known on the very first render for a board that was already old when the page was served', () => {
    const { result } = mount({ initialBoard: boardBuiltAt(BOARD_A, iso(T0 - 10 * 60_000)) });
    expect(result.current.assessment).toMatchObject({ mode: 'last-known', reason: 'old' });
  });
});

describe('useBoardFeed: the stream', () => {
  it('works with no EventSource at all: it polls, and says the stream is paused after 10 s', async () => {
    const { result, fetchBoard } = mount({ createEventSource: () => null });
    await advance(11_000);
    expect(result.current.assessment).toEqual({ mode: 'live', streamPaused: true });

    await advance(50_000);
    expect(fetchBoard).toHaveBeenCalledTimes(1);
  });

  it('a stream that never opens counts as gapped from the start', async () => {
    const { result, fetchBoard } = mount();
    fetchBoard.mockRejectedValue(unreachable());

    await advance(61_000);

    expect(result.current.assessment).toMatchObject({ mode: 'last-known', reason: 'offline' });
  });

  it('survives a factory that throws, as a stream that is down', async () => {
    const { result } = mount({
      createEventSource: () => {
        throw new Error('no EventSource');
      },
    });
    await advance(11_000);

    expect(result.current.assessment).toEqual({ mode: 'live', streamPaused: true });
  });

  it('opens a new stream 5 s after the browser gives up on one', async () => {
    const { streams, stream } = mount();
    await openStream(stream());

    await breakStream(stream(), true);
    expect(streams).toHaveLength(1);
    await advance(4_999);
    expect(streams).toHaveLength(1);
    await advance(1);

    expect(streams).toHaveLength(2);
    expect(streams[0].closed).toBe(true);
  });

  it('leaves a stream the browser is still retrying alone', async () => {
    const { streams, stream } = mount();
    await openStream(stream());

    await breakStream(stream(), false);
    await advance(30_000);

    expect(streams).toHaveLength(1);
  });
});

describe('useBoardFeed: a screen the back end refuses', () => {
  it.each([401, 403, 404])('calls onUnpaired once when a refetch is refused with %i, and still shows Last known', async (status) => {
    const { result, stream, fetchBoard, onUnpaired } = mount();
    await openStream(stream());
    fetchBoard.mockRejectedValue(new BoardFetchError('refused', status));
    await breakStream(stream());

    await advance(61_000);

    expect(onUnpaired).toHaveBeenCalledTimes(1);
    expect(result.current.assessment).toMatchObject({ mode: 'last-known' });
  });

  it('calls onUnpaired once, however many polls are refused', async () => {
    const { stream, fetchBoard, onUnpaired } = mount();
    await openStream(stream());
    fetchBoard.mockRejectedValue(new BoardFetchError('refused', 401));

    await advance(5 * 60_000);

    expect(fetchBoard.mock.calls.length).toBeGreaterThan(3);
    expect(onUnpaired).toHaveBeenCalledTimes(1);
  });

  it('does not call onUnpaired for a server error', async () => {
    const { stream, fetchBoard, onUnpaired } = mount();
    await openStream(stream());
    fetchBoard.mockRejectedValue(new BoardFetchError('unreachable', 500));

    await advance(61_000);

    expect(onUnpaired).not.toHaveBeenCalled();
  });
});

describe('useBoardFeed: clean-up on unmount', () => {
  it('closes the stream, clears every timer, aborts the request in flight and refetches nothing afterwards', async () => {
    const { stream, fetchBoard, unmount } = mount();
    await openStream(stream());
    const signals: AbortSignal[] = [];
    fetchBoard.mockClear();
    fetchBoard.mockImplementation((signal) => {
      signals.push(signal);
      return new Promise<FetchedBoard>(() => undefined);
    });
    await emit(stream());
    expect(signals).toHaveLength(1);

    unmount();

    expect(stream().closed).toBe(true);
    expect(signals[0].aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
    fetchBoard.mockClear();
    await advance(10 * 60_000);
    expect(fetchBoard).not.toHaveBeenCalled();
  });

  it('ignores an answer that arrives after unmount', async () => {
    const { stream, fetchBoard, unmount } = mount();
    await openStream(stream());
    fetchBoard.mockClear();
    let release: (value: FetchedBoard) => void = () => undefined;
    fetchBoard.mockImplementation(() => new Promise<FetchedBoard>((resolve) => (release = resolve)));
    await emit(stream());
    const errors = vi.spyOn(console, 'error').mockImplementation(() => undefined);

    unmount();
    await act(async () => release(builtNow()));

    expect(errors).not.toHaveBeenCalled();
    errors.mockRestore();
  });

  it('closes a stream retry that is waiting, and opens no new stream after unmount', async () => {
    const { streams, stream, unmount } = mount();
    await openStream(stream());
    await breakStream(stream(), true);

    expect(vi.getTimerCount()).toBeGreaterThan(0);
    unmount();
    expect(vi.getTimerCount()).toBe(0);
    await advance(60_000);

    expect(streams).toHaveLength(1);
  });
});
