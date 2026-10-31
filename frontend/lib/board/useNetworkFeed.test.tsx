import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FakeStream } from '@/test/fakeStream';
import { BOARD_BODY } from '@/test/fixtures/network';
import { NetworkFetchError, type FetchedNetworkBoard } from '@/lib/network/browser';
import { parseBoard } from '@/lib/network/parse';
import type { NetworkBoard } from '@/lib/network/types';
import { STALE_AFTER_MS } from './liveness';
import { useNetworkFeed, type NetworkFeedOptions } from './useNetworkFeed';

// TEN-070: the network board kept current, and the states it can be in. The stream says "something
// changed" and the page reads the WHOLE board again; a refusal removes every figure (not available); a
// failure keeps the last good board as Last known; and the board of one network is never shown as the
// board of another.

const T0 = Date.parse('2026-10-23T13:12:00Z');
const iso = (ms: number) => new Date(ms).toISOString();

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(T0);
});
afterEach(() => vi.useRealTimers());

function boardAt(ms: number, services = BOARD_BODY.entries.length): NetworkBoard {
  const board = parseBoard(BOARD_BODY, 'backend');
  return { ...board, generatedAt: iso(ms), entries: board.entries.slice(0, services) };
}

function builtNow(): FetchedNetworkBoard {
  return { board: boardAt(Date.now()), serverTime: Date.now() };
}

function mount(over: Partial<NetworkFeedOptions> = {}, networkId = 'net-sample') {
  const fetchBoard = vi.fn<(id: string, signal: AbortSignal) => Promise<FetchedNetworkBoard>>(async () => builtNow());
  const streams: FakeStream[] = [];
  const createEventSource = vi.fn((_id: string) => {
    const stream = new FakeStream();
    streams.push(stream);
    return stream;
  });
  const options = { networkId, fetchBoard, createEventSource, ...over } satisfies NetworkFeedOptions;
  const hook = renderHook((props: { networkId: string }) => useNetworkFeed({ ...options, networkId: props.networkId }), {
    initialProps: { networkId },
  });
  return { ...hook, fetchBoard, createEventSource, streams, stream: () => streams[streams.length - 1]! };
}

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe('useNetworkFeed: reading', () => {
  it('is loading until the first board has been read, then ready and live', async () => {
    const m = mount();
    expect(m.result.current.status).toBe('loading');
    await advance(0);
    expect(m.result.current.status).toBe('ready');
    if (m.result.current.status === 'ready') {
      expect(m.result.current.board.entries).toHaveLength(4);
      expect(m.result.current.assessment.mode).toBe('live');
    }
  });

  it('reads the board of the network it was given, and opens the stream of that network', async () => {
    const m = mount();
    await advance(0);
    expect(m.fetchBoard).toHaveBeenCalledWith('net-sample', expect.any(AbortSignal));
    expect(m.createEventSource).toHaveBeenCalledWith('net-sample');
  });

  it('reads the whole board again when the network says it changed, and when the stream (re)opens', async () => {
    const m = mount();
    await advance(0);
    const before = m.fetchBoard.mock.calls.length;
    await act(async () => m.stream().open());
    await advance(0);
    expect(m.fetchBoard.mock.calls.length).toBeGreaterThan(before);
    const afterOpen = m.fetchBoard.mock.calls.length;
    await act(async () => m.stream().emit('network-board', '{"changedAt":"2026-10-23T13:12:00+00:00"}'));
    await advance(0);
    expect(m.fetchBoard.mock.calls.length).toBeGreaterThan(afterOpen);
  });

  it('listens for network-board and scope-ended, and for no event of the tenant’s board', async () => {
    const m = mount();
    await advance(0);
    expect(m.stream().listenerNames().sort()).toEqual(['network-board', 'scope-ended']);
  });

  it('reads again every minute as a fallback', async () => {
    const m = mount();
    await advance(0);
    const before = m.fetchBoard.mock.calls.length;
    await advance(61_000);
    expect(m.fetchBoard.mock.calls.length).toBeGreaterThan(before);
  });

  it('never replaces the board it holds with an older one', async () => {
    const m = mount();
    await advance(0);
    m.fetchBoard.mockResolvedValue({ board: boardAt(T0 - 30_000, 1), serverTime: Date.now() });
    await act(async () => m.stream().emit('network-board'));
    await advance(0);
    if (m.result.current.status === 'ready') expect(m.result.current.board.entries).toHaveLength(4);
  });
});

describe('useNetworkFeed: not available', () => {
  it.each([401, 403, 404])('a %s removes every figure and closes the stream', async (status) => {
    const m = mount();
    await advance(0);
    m.fetchBoard.mockRejectedValue(new NetworkFetchError('refused', status));
    await act(async () => m.stream().emit('network-board'));
    await advance(0);
    expect(m.result.current.status).toBe('unavailable');
    expect(m.stream().closed).toBe(true);
  });

  it('the scope-ended event makes it read again, and a refusal then is not available', async () => {
    const m = mount();
    await advance(0);
    m.fetchBoard.mockRejectedValue(new NetworkFetchError('refused', 404));
    await act(async () => m.stream().emit('scope-ended', '{}'));
    await advance(0);
    expect(m.result.current.status).toBe('unavailable');
  });

  it('is not available at once when the very first read is refused', async () => {
    const m = mount({ fetchBoard: vi.fn(async () => Promise.reject(new NetworkFetchError('refused', 404))) });
    await advance(0);
    expect(m.result.current.status).toBe('unavailable');
  });
});

describe('useNetworkFeed: last known', () => {
  it('keeps the last good board as last known when the reads fail and the stream is down', async () => {
    const m = mount();
    await advance(0);
    await act(async () => m.stream().open());
    await advance(0);
    m.fetchBoard.mockRejectedValue(new NetworkFetchError('unreachable', 503));
    await act(async () => m.stream().fail());
    await advance(61_000);
    expect(m.result.current.status).toBe('ready');
    if (m.result.current.status === 'ready') {
      expect(m.result.current.assessment.mode).toBe('last-known');
      expect(m.result.current.board.entries).toHaveLength(4);
    }
  });

  it('is last known when the board it holds is too old, even though nothing failed', async () => {
    const m = mount();
    await advance(0);
    m.fetchBoard.mockResolvedValue({ board: boardAt(T0), serverTime: Date.now() });
    await advance(STALE_AFTER_MS + 61_000);
    if (m.result.current.status === 'ready') expect(m.result.current.assessment.mode).toBe('last-known');
  });

  it('is last known when the answer cannot be read, never a blank board', async () => {
    const m = mount();
    await advance(0);
    m.fetchBoard.mockRejectedValue(new NetworkFetchError('unreadable', 502));
    await act(async () => m.stream().emit('network-board'));
    await advance(0);
    if (m.result.current.status === 'ready') {
      expect(m.result.current.assessment.mode).toBe('last-known');
      expect(m.result.current.board.entries).toHaveLength(4);
    }
  });

  it('says it is offline when the very first read fails and there is no board to keep', async () => {
    const m = mount({ fetchBoard: vi.fn(async () => Promise.reject(new NetworkFetchError('unreachable', 503))) });
    await advance(0);
    expect(m.result.current.status).toBe('offline');
  });

  it('recovers: a good read after a failure is live again', async () => {
    const m = mount();
    await advance(0);
    m.fetchBoard.mockRejectedValueOnce(new NetworkFetchError('unreachable', 503));
    await act(async () => m.stream().emit('network-board'));
    await advance(0);
    m.fetchBoard.mockImplementation(async () => builtNow());
    await act(async () => m.stream().emit('network-board'));
    await advance(0);
    if (m.result.current.status === 'ready') expect(m.result.current.assessment.mode).toBe('live');
  });
});

describe('useNetworkFeed: one network at a time', () => {
  it('drops the figures of the old network when it is given another, and never shows them as the new one’s', async () => {
    const m = mount();
    await advance(0);
    expect(m.result.current.status).toBe('ready');
    const first = m.stream();
    m.fetchBoard.mockImplementation(() => new Promise(() => undefined));
    m.rerender({ networkId: 'net-other' });
    expect(m.result.current.status).toBe('loading');
    expect(first.closed).toBe(true);
    expect(m.createEventSource).toHaveBeenLastCalledWith('net-other');
  });

  it('closes the stream and stops reading when it goes away', async () => {
    const m = mount();
    await advance(0);
    const stream = m.stream();
    m.unmount();
    expect(stream.closed).toBe(true);
    const calls = m.fetchBoard.mock.calls.length;
    await advance(120_000);
    expect(m.fetchBoard.mock.calls.length).toBe(calls);
  });
});
