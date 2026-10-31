import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FakeStream } from '@/test/fakeStream';
import { BOARD_A, BOARD_B, boardBuiltAt, GENERATED_AT } from '@/test/fixtures/board';
import { BoardFetchError, type FetchedBoard } from './client';
import { OWN_SCOPE, type WallScope } from './scope';
import { useBoardFeed, type BoardFeedOptions } from './useBoardFeed';

// TEN-072: the wall's last known figures are kept PER SCOPE. A screen that shows its own board and is then
// set to a network (or back, or falls back) drops the figures of the old scope at once: they are never shown
// again as the last known figures of the new one, the stream is opened again for the new scope, and a refused
// or failed read cannot bring the old scope back.

const T0 = Date.parse(GENERATED_AT);
const iso = (ms: number) => new Date(ms).toISOString();
const NETWORK: WallScope = { boardScope: 'network', scopeVersion: 3, fallback: false, networkName: 'West Dorset system' };
const FELL_BACK: WallScope = { boardScope: 'tenant', scopeVersion: 4, fallback: true, networkName: null };
const NETWORK_BOARD = { ...boardBuiltAt(BOARD_B, iso(T0)), organisation: null };

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(T0);
});
afterEach(() => vi.useRealTimers());

const fresh = (board = BOARD_A, scope: WallScope = OWN_SCOPE): FetchedBoard => ({ board: boardBuiltAt(board, iso(Date.now())), serverTime: Date.now(), scope });

function mount(over: Partial<BoardFeedOptions> = {}) {
  const fetchBoard = vi.fn<(signal: AbortSignal) => Promise<FetchedBoard>>(async () => fresh());
  const streams: { scope: WallScope; stream: FakeStream }[] = [];
  const createEventSource = vi.fn((scope: WallScope) => {
    const stream = new FakeStream();
    streams.push({ scope, stream });
    return stream;
  });
  const options: BoardFeedOptions = { initialBoard: BOARD_A, serverTime: T0, fetchBoard, createEventSource, onUnpaired: vi.fn(), ...over };
  const hook = renderHook(() => useBoardFeed(options));
  return { ...hook, fetchBoard, createEventSource, streams };
}

const advance = (ms: number) => act(async () => void (await vi.advanceTimersByTimeAsync(ms)));
const settle = () => advance(0);
const openLast = async (streams: { stream: FakeStream }[]) => {
  await act(async () => streams[streams.length - 1]!.stream.open());
  await settle();
};

describe('useBoardFeed: the scope', () => {
  it('says the screen shows its own board until the back end says otherwise, and takes the first scope the page read', () => {
    expect(mount().result.current.scope).toEqual(OWN_SCOPE);
    expect(mount({ initialScope: NETWORK }).result.current.scope).toEqual(NETWORK);
  });

  it('opens the stream for the scope the screen shows', () => {
    const { createEventSource } = mount({ initialScope: NETWORK });
    expect(createEventSource).toHaveBeenCalledWith(NETWORK);
  });

  it('drops the figures of the old scope the moment a read says the board changed, even if the new board is older', async () => {
    const { result, fetchBoard, streams } = mount();
    await openLast(streams);
    // The network's board was built a minute before the own board that is held.
    fetchBoard.mockResolvedValueOnce({ board: { ...NETWORK_BOARD, generatedAt: iso(T0 - 60_000) }, serverTime: T0, scope: NETWORK });
    await advance(60_000);
    expect(result.current.scope).toEqual(NETWORK);
    expect(result.current.board.entries.map((entry) => entry.serviceId)).toEqual(NETWORK_BOARD.entries.map((entry) => entry.serviceId));
    for (const entry of BOARD_A.entries) expect(result.current.board.entries.some((held) => held.serviceId === entry.serviceId)).toBe(false);
  });

  it('opens the stream again for the new scope and closes the old one', async () => {
    const { fetchBoard, createEventSource, streams } = mount();
    await openLast(streams);
    fetchBoard.mockResolvedValueOnce(fresh(NETWORK_BOARD, NETWORK));
    // The own stream beats every 15 s (KI-54): a silent one is closed and opened again by the watchdog, which is
    // not what this test is about, so it is kept alive up to the read of the minute.
    for (let beat = 0; beat < 4; beat++) {
      await act(async () => streams[0]!.stream.emit('heartbeat'));
      await advance(15_000);
    }
    expect(createEventSource).toHaveBeenCalledTimes(2);
    expect(createEventSource).toHaveBeenLastCalledWith(NETWORK);
    expect(streams[0]!.stream.closed).toBe(true);
  });

  it('listens to a network stream for network-board and scope-ended, and to a tenant stream for board events only', async () => {
    const own = mount();
    expect(own.streams[0]!.stream.listenerNames()).toEqual(expect.arrayContaining(['board', 'board.updated']));
    expect(own.streams[0]!.stream.listenerNames()).not.toContain('network-board');

    const network = mount({ initialScope: NETWORK });
    expect(network.streams[0]!.stream.listenerNames()).toEqual(expect.arrayContaining(['network-board', 'scope-ended']));
    expect(network.streams[0]!.stream.listenerNames()).not.toContain('board');
  });

  it('reads the board and the setting again on network-board and on scope-ended', async () => {
    const { fetchBoard, streams } = mount({ initialScope: NETWORK });
    await openLast(streams);
    for (const type of ['network-board', 'scope-ended']) {
      fetchBoard.mockClear();
      await act(async () => streams[0]!.stream.emit(type));
      await settle();
      expect(fetchBoard, type).toHaveBeenCalledTimes(1);
    }
  });

  it('keeps the new scope’s figures as last known when a later read fails, and never brings the old scope back', async () => {
    const { result, fetchBoard, streams } = mount();
    await openLast(streams);
    fetchBoard.mockResolvedValueOnce(fresh(NETWORK_BOARD, NETWORK));
    await advance(60_000);
    fetchBoard.mockRejectedValue(new BoardFetchError('unreadable', 502));
    await advance(60_000);
    expect(result.current.assessment.mode).toBe('last-known');
    expect(result.current.scope).toEqual(NETWORK);
    expect(result.current.board.entries.map((entry) => entry.serviceId)).toEqual(NETWORK_BOARD.entries.map((entry) => entry.serviceId));
  });

  it('starts the new scope live: a failure that was running for the old scope does not make the new board last known', async () => {
    const { result, fetchBoard, streams } = mount();
    await openLast(streams);
    fetchBoard.mockRejectedValueOnce(new BoardFetchError('unreadable', 502));
    await advance(60_000);
    expect(result.current.assessment.mode).toBe('last-known');
    fetchBoard.mockResolvedValueOnce(fresh(NETWORK_BOARD, NETWORK));
    await advance(60_000);
    expect(result.current.assessment.mode).toBe('live');
  });

  it('still never replaces a board of the same scope with an older one', async () => {
    const { result, fetchBoard, streams } = mount();
    await openLast(streams);
    const held = result.current.board.generatedAt;
    fetchBoard.mockResolvedValueOnce({ board: { ...BOARD_A, generatedAt: iso(T0 - 120_000) }, serverTime: T0, scope: OWN_SCOPE });
    await advance(60_000);
    expect(result.current.board.generatedAt).toBe(held);
  });

  it('reports a fall back with the flag, and remembers the name of the network the screen was showing', async () => {
    const { result, fetchBoard, streams } = mount({ initialScope: NETWORK, initialBoard: NETWORK_BOARD });
    await openLast(streams);
    expect(result.current.lastNetworkName).toBe('West Dorset system');
    fetchBoard.mockResolvedValueOnce(fresh(BOARD_A, FELL_BACK));
    await advance(60_000);
    expect(result.current.scope).toEqual(FELL_BACK);
    expect(result.current.lastNetworkName).toBe('West Dorset system');
    expect(result.current.board.entries.map((entry) => entry.serviceId)).toEqual(BOARD_A.entries.map((entry) => entry.serviceId));
  });

  it('forgets the remembered network when the screen is set to the board of another network', async () => {
    const { result, fetchBoard, streams } = mount({ initialScope: NETWORK, initialBoard: NETWORK_BOARD });
    await openLast(streams);
    fetchBoard.mockResolvedValueOnce(fresh(NETWORK_BOARD, { ...NETWORK, scopeVersion: 5, networkName: 'North system' }));
    await advance(60_000);
    expect(result.current.lastNetworkName).toBe('North system');
  });

  it('refusal of a read still sends the screen back to pairing, in any scope', async () => {
    const onUnpaired = vi.fn();
    const { fetchBoard } = mount({ initialScope: NETWORK, onUnpaired });
    fetchBoard.mockRejectedValueOnce(new BoardFetchError('refused', 404));
    await advance(60_000);
    expect(onUnpaired).toHaveBeenCalledTimes(1);
  });
});
