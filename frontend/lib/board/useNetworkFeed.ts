import { useEffect, useRef, useState } from 'react';
import {
  fetchNetworkBoard,
  NETWORK_REFUSED_STATUSES,
  networkEventsUrl,
  NetworkFetchError,
  type FetchedNetworkBoard,
} from '@/lib/network/browser';
import type { NetworkBoard } from '@/lib/network/types';
import { assessBoard, FETCH_TIMEOUT_MS, MAX_FUTURE_SKEW_MS, POLL_INTERVAL_MS, STREAM_RETRY_MS, type Assessment, type Health } from './liveness';
import type { StreamSource } from './useBoardFeed';

// Keeps a network's board current and says, at every moment, what the page may show (TEN-070). It is the
// wall's rules (useBoardFeed) over a network's stream:
//
//  - the stream says "something changed" and the page reads the WHOLE board again; it never patches one
//    from an event, so a missed event is harmless;
//  - a read that is REFUSED (401, 403, 404, or the stream's `scope-ended` followed by a refusal) removes
//    every figure: the network is not available to this viewer, and nothing of it is kept;
//  - a read that fails keeps the last good board and turns it to Last known; a board too old does too;
//    nothing is ever blanked, and a board is never replaced by an older one;
//  - a board of one network is never shown as another's: a new network id starts again from nothing.

export type NetworkFeedOptions = {
  /** The id of the network the server offered. */
  networkId: string;
  fetchBoard?: (networkId: string, signal: AbortSignal) => Promise<FetchedNetworkBoard>;
  /** Opens the live stream of the network, or returns null when there is none. */
  createEventSource?: (networkId: string) => StreamSource | null;
  /** The browser's clock in epoch ms. */
  now?: () => number;
};

export type NetworkFeed =
  | { status: 'loading' }
  | { status: 'unavailable' }
  /** No board was ever read and the reads fail: nothing to keep as last known. */
  | { status: 'offline'; since: string }
  | { status: 'ready'; board: NetworkBoard; assessment: Assessment };

/** The events that mean the board changed or that the viewer's scope ended. */
export const NETWORK_FEED_EVENTS = ['network-board', 'scope-ended'] as const;

const TICK_MS = 1_000;
const EVENT_SOURCE_CLOSED = 2;
const NO_PROBLEMS: Health = { streamDownSince: null, failingSince: null, unreadableSince: null };

function openStream(networkId: string): StreamSource | null {
  return typeof EventSource === 'undefined' ? null : new EventSource(networkEventsUrl(networkId));
}

type State = { networkId: string; feed: NetworkFeed };

export function useNetworkFeed(options: NetworkFeedOptions): NetworkFeed {
  const [state, setState] = useState<State>({ networkId: options.networkId, feed: { status: 'loading' } });
  const latest = useRef(options);
  useEffect(() => {
    latest.current = options;
  });

  const networkId = options.networkId;
  useEffect(() => {
    const opts = () => latest.current;
    const now = () => (opts().now ?? Date.now)();

    let board: NetworkBoard | null = null;
    let offset = 0;
    const health: Health = { ...NO_PROBLEMS };
    let stopped = false;
    let refused = false;
    let inFlight: AbortController | null = null;
    let queued = false;
    let fetchTimer: ReturnType<typeof setTimeout> | null = null;
    let source: StreamSource | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    function publish(feed: NetworkFeed) {
      if (stopped) return;
      setState((previous) => (previous.networkId === networkId && sameFeed(previous.feed, feed) ? previous : { networkId, feed }));
    }

    function evaluate() {
      if (stopped || refused) return;
      if (board === null) {
        const since = health.failingSince ?? health.unreadableSince;
        publish(since === null ? { status: 'loading' } : { status: 'offline', since: new Date(since + offset).toISOString() });
        return;
      }
      publish({ status: 'ready', board, assessment: assessBoard({ generatedAt: board.generatedAt, nowLocal: now(), clockOffsetMs: offset, health }) });
    }

    function refuse() {
      refused = true;
      board = null;
      source?.close();
      source = null;
      publish({ status: 'unavailable' });
    }

    function accept(result: FetchedNetworkBoard) {
      if (result.serverTime !== null) offset = result.serverTime - now();
      const builtAt = Date.parse(result.board.generatedAt);
      if (!Number.isFinite(builtAt) || builtAt - (now() + offset) > MAX_FUTURE_SKEW_MS) {
        // A board from the future cannot be right, and keeping it would refuse every real one.
        health.unreadableSince ??= now();
      } else {
        health.failingSince = null;
        health.unreadableSince = null;
        if (board === null || builtAt >= Date.parse(board.generatedAt)) board = result.board;
      }
      evaluate();
    }

    function fail(error: unknown) {
      const known = error instanceof NetworkFetchError ? error : null;
      if (known?.kind === 'refused' && known.status !== null && NETWORK_REFUSED_STATUSES.includes(known.status)) {
        refuse();
        return;
      }
      if (known?.kind === 'unreadable') health.unreadableSince ??= now();
      else health.failingSince ??= now();
      evaluate();
    }

    function refetch() {
      if (stopped || refused) return;
      if (inFlight !== null) {
        queued = true;
        return;
      }
      const controller = new AbortController();
      inFlight = controller;
      let settled = false;
      const finish = () => {
        if (fetchTimer !== null) clearTimeout(fetchTimer);
        fetchTimer = null;
        if (inFlight === controller) inFlight = null;
        if (queued && !stopped && !refused) {
          queued = false;
          refetch();
        }
      };
      // A request that never answers is abandoned, counted as a failure, and the next poll can run.
      fetchTimer = setTimeout(() => {
        if (settled) return;
        settled = true;
        controller.abort();
        fail(new NetworkFetchError('unreachable'));
        finish();
      }, FETCH_TIMEOUT_MS);
      void Promise.resolve()
        .then(() => (opts().fetchBoard ?? fetchNetworkBoard)(networkId, controller.signal))
        .then(
          (result) => {
            if (settled || stopped) return;
            settled = true;
            accept(result);
            finish();
          },
          (error: unknown) => {
            if (settled || stopped) return;
            settled = true;
            fail(error);
            finish();
          },
        );
    }

    function connect() {
      if (stopped || refused) return;
      health.streamDownSince ??= now();
      let opened: StreamSource | null = null;
      try {
        opened = (opts().createEventSource ?? openStream)(networkId);
      } catch {
        opened = null;
      }
      source = opened;
      if (opened === null) {
        evaluate();
        return;
      }
      const current = opened;
      current.onopen = () => {
        health.streamDownSince = null;
        evaluate();
        refetch();
      };
      current.onerror = () => {
        health.streamDownSince ??= now();
        if (current.readyState === EVENT_SOURCE_CLOSED) {
          current.close();
          if (retryTimer === null && !stopped && !refused) {
            retryTimer = setTimeout(() => {
              retryTimer = null;
              connect();
            }, STREAM_RETRY_MS);
          }
        }
        evaluate();
      };
      // `scope-ended` reads again too: the read is what says whether the viewer may still see the network.
      for (const name of NETWORK_FEED_EVENTS) current.addEventListener(name, refetch);
    }

    connect();
    refetch();
    const poll = setInterval(refetch, POLL_INTERVAL_MS);
    const tick = setInterval(evaluate, TICK_MS);

    return () => {
      stopped = true;
      clearInterval(poll);
      clearInterval(tick);
      if (retryTimer !== null) clearTimeout(retryTimer);
      if (fetchTimer !== null) clearTimeout(fetchTimer);
      inFlight?.abort();
      source?.close();
    };
  }, [networkId]);

  // The board of another network is never shown for this one: until the new network has its own read,
  // it is loading.
  return state.networkId === networkId ? state.feed : { status: 'loading' };
}

const MINUTE_MS = 60_000;

function sameAssessment(a: Assessment, b: Assessment): boolean {
  if (a.mode === 'live' || b.mode === 'live') return a.mode === 'live' && b.mode === 'live' && a.streamPaused === b.streamPaused;
  return a.reason === b.reason && a.since === b.since && a.asOf === b.asOf && Math.floor(Date.parse(a.now) / MINUTE_MS) === Math.floor(Date.parse(b.now) / MINUTE_MS);
}

/** Same words and same minute on the clock: nothing on screen would change. */
function sameFeed(a: NetworkFeed, b: NetworkFeed): boolean {
  if (a.status !== b.status) return false;
  if (a.status === 'ready' && b.status === 'ready') return a.board === b.board && sameAssessment(a.assessment, b.assessment);
  if (a.status === 'offline' && b.status === 'offline') return a.since === b.since;
  return true;
}
