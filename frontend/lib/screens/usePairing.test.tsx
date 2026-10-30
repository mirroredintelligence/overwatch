import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ScreenClientError } from './client';
import { POLL_INTERVAL_MS, RETRY_UNAVAILABLE_MS, usePairing, type PairingApi } from './usePairing';

// The wall display's side of pairing, driven by fake timers: on opening it tries its device cookie
// first; with none it asks for a code, shows it, and asks every three seconds whether a lead has
// connected it. An expired code is replaced by a new one without anyone touching the screen.

function failure(kind: ScreenClientError['kind'], retryAfterMs: number | null = null) {
  const error = new ScreenClientError(kind);
  error.retryAfterMs = retryAfterMs;
  return error;
}

function api(over: Partial<PairingApi> = {}) {
  let n = 0;
  const calls: PairingApi = {
    renew: vi.fn(async () => {
      throw failure('not-found');
    }),
    start: vi.fn(async () => {
      n += 1;
      return { pairingId: `pairing-${n}`, code: n === 1 ? '482913' : '271828', expiresAt: '2026-10-30T09:10:00Z' };
    }),
    poll: vi.fn(async () => 'waiting' as const),
    ...over,
  };
  return calls;
}

function mount(calls: PairingApi) {
  const onPaired = vi.fn();
  const hook = renderHook(() => usePairing({ api: calls, onPaired }));
  return { ...hook, onPaired };
}

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
});

describe('usePairing: opening', () => {
  it('tries the screen’s own session first, and goes straight on when it has one, asking for no code', async () => {
    const calls = api({ renew: vi.fn(async () => undefined) });
    const { onPaired } = mount(calls);
    await advance(0);
    expect(onPaired).toHaveBeenCalledTimes(1);
    expect(calls.start).not.toHaveBeenCalled();
  });

  it('asks for a code, and shows it as two groups of three, when it has no session to renew', async () => {
    const calls = api();
    const { result } = mount(calls);
    expect(result.current).toEqual({ kind: 'connecting' });
    await advance(0);
    expect(result.current).toEqual({ kind: 'code', code: '482 913', expiresAt: '2026-10-30T09:10:00Z' });
    expect(calls.renew).toHaveBeenCalledTimes(1);
    expect(calls.start).toHaveBeenCalledTimes(1);
  });

  it('says it is connecting, and tries again every ten seconds, while the back end cannot answer the renewal, and never starts a pairing then', async () => {
    const calls = api({ renew: vi.fn(async () => { throw failure('unavailable'); }) });
    const { result } = mount(calls);
    await advance(0);
    expect(result.current).toEqual({ kind: 'connecting' });
    await advance(RETRY_UNAVAILABLE_MS);
    await advance(RETRY_UNAVAILABLE_MS);
    expect(calls.renew).toHaveBeenCalledTimes(3);
    expect(calls.start).not.toHaveBeenCalled();
  });
});

describe('usePairing: waiting for a lead', () => {
  it('asks every three seconds, with the id it was given, and never two at once', async () => {
    let release: () => void = () => {};
    const slow = vi.fn(() => new Promise<'waiting'>((resolve) => (release = () => resolve('waiting'))));
    const calls = api({ poll: slow });
    mount(calls);
    await advance(0);
    await advance(POLL_INTERVAL_MS);
    expect(slow).toHaveBeenCalledTimes(1);
    expect(slow).toHaveBeenCalledWith('pairing-1', expect.anything());
    await advance(POLL_INTERVAL_MS * 3);
    expect(slow).toHaveBeenCalledTimes(1);
    release();
    await advance(POLL_INTERVAL_MS);
    expect(slow).toHaveBeenCalledTimes(2);
  });

  it('goes on to the board when the answer is paired, and asks no more', async () => {
    const poll = vi.fn<PairingApi['poll']>().mockResolvedValueOnce('waiting').mockResolvedValueOnce('paired');
    const calls = api({ poll });
    const { onPaired } = mount(calls);
    await advance(0);
    await advance(POLL_INTERVAL_MS);
    expect(onPaired).not.toHaveBeenCalled();
    await advance(POLL_INTERVAL_MS);
    expect(onPaired).toHaveBeenCalledTimes(1);
    await advance(POLL_INTERVAL_MS * 5);
    expect(poll).toHaveBeenCalledTimes(2);
  });

  it('asks for a new code at once when the code has expired, and shows it', async () => {
    const poll = vi.fn<PairingApi['poll']>().mockResolvedValueOnce('expired').mockResolvedValue('waiting');
    const calls = api({ poll });
    const { result } = mount(calls);
    await advance(0);
    expect(result.current).toMatchObject({ kind: 'code', code: '482 913' });
    await advance(POLL_INTERVAL_MS);
    expect(calls.start).toHaveBeenCalledTimes(2);
    expect(result.current).toMatchObject({ kind: 'code', code: '271 828' });
    await advance(POLL_INTERVAL_MS);
    expect(poll).toHaveBeenLastCalledWith('pairing-2', expect.anything());
  });

  it('asks for a new code when the back end no longer knows the pairing', async () => {
    const poll = vi.fn<PairingApi['poll']>().mockRejectedValueOnce(failure('not-found')).mockResolvedValue('waiting');
    const calls = api({ poll });
    const { result } = mount(calls);
    await advance(0);
    await advance(POLL_INTERVAL_MS);
    expect(calls.start).toHaveBeenCalledTimes(2);
    expect(result.current).toMatchObject({ code: '271 828' });
  });

  it('keeps the code on screen and asks again when an answer fails', async () => {
    const poll = vi.fn<PairingApi['poll']>().mockRejectedValueOnce(failure('unavailable')).mockRejectedValueOnce(failure('throttled', 600_000)).mockResolvedValue('waiting');
    const calls = api({ poll });
    const { result } = mount(calls);
    await advance(0);
    await advance(POLL_INTERVAL_MS * 3);
    expect(poll.mock.calls.length).toBeGreaterThanOrEqual(3);
    expect(result.current).toMatchObject({ kind: 'code', code: '482 913' });
    expect(calls.start).toHaveBeenCalledTimes(1);
  });

  it('collects a device token the back end already gave, by renewing, when the BFF says connecting', async () => {
    const renew = vi.fn<PairingApi['renew']>().mockRejectedValueOnce(failure('not-found')).mockResolvedValue(undefined);
    const poll = vi.fn<PairingApi['poll']>().mockResolvedValue('connecting');
    const { onPaired } = mount(api({ renew, poll }));
    await advance(0);
    await advance(POLL_INTERVAL_MS);
    expect(renew).toHaveBeenCalledTimes(2);
    expect(onPaired).toHaveBeenCalledTimes(1);
  });
});

describe('usePairing: when a code cannot be had', () => {
  it('says so and waits a minute by default, or as long as the answer says, then asks again', async () => {
    const start = vi
      .fn<PairingApi['start']>()
      .mockRejectedValueOnce(failure('throttled'))
      .mockRejectedValueOnce(failure('throttled', 120_000))
      .mockResolvedValue({ pairingId: 'pairing-9', code: '314159', expiresAt: '2026-10-30T09:10:00Z' });
    const { result } = mount(api({ start }));
    await advance(0);
    expect(result.current).toEqual({ kind: 'throttled' });
    await advance(59_000);
    expect(start).toHaveBeenCalledTimes(1);
    await advance(1_000);
    expect(start).toHaveBeenCalledTimes(2);
    await advance(119_000);
    expect(start).toHaveBeenCalledTimes(2);
    await advance(1_000);
    expect(result.current).toMatchObject({ kind: 'code', code: '314 159' });
  });

  it('says it is unavailable and asks again every ten seconds when the back end cannot be reached', async () => {
    const start = vi.fn<PairingApi['start']>().mockRejectedValueOnce(failure('unavailable')).mockRejectedValueOnce(failure('not-found')).mockResolvedValue({ pairingId: 'p', code: '314159', expiresAt: '2026-10-30T09:10:00Z' });
    const { result } = mount(api({ start }));
    await advance(0);
    expect(result.current).toEqual({ kind: 'unavailable' });
    await advance(RETRY_UNAVAILABLE_MS);
    expect(start).toHaveBeenCalledTimes(2);
    expect(result.current).toEqual({ kind: 'unavailable' });
    await advance(RETRY_UNAVAILABLE_MS);
    expect(result.current).toMatchObject({ code: '314 159' });
  });
});

describe('usePairing: leaving', () => {
  it('stops asking when the page is left, even with an answer in flight', async () => {
    let release: (value: 'paired') => void = () => {};
    const poll = vi.fn(() => new Promise<'paired'>((resolve) => (release = resolve)));
    const calls = api({ poll });
    const { unmount, onPaired } = mount(calls);
    await advance(0);
    await advance(POLL_INTERVAL_MS);
    unmount();
    release('paired');
    await advance(POLL_INTERVAL_MS * 5);
    expect(onPaired).not.toHaveBeenCalled();
    expect(poll).toHaveBeenCalledTimes(1);
  });

  it('aborts the request in flight when the page is left', async () => {
    const signals: AbortSignal[] = [];
    const calls = api({ poll: vi.fn((_id, signal) => ((signals.push(signal as AbortSignal)), new Promise<'waiting'>(() => {}))) });
    const { unmount } = mount(calls);
    await advance(0);
    await advance(POLL_INTERVAL_MS);
    unmount();
    expect(signals[0]?.aborted).toBe(true);
  });
});
