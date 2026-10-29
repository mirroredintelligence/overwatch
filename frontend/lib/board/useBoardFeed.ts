import { useEffect, useRef, useState } from 'react';
import { BoardFetchError, fetchBoardFromBff, REFUSED_STATUSES, type FetchedBoard } from './client';
import {
  assessBoard,
  FETCH_TIMEOUT_MS,
  MAX_FUTURE_SKEW_MS,
  POLL_INTERVAL_MS,
  STREAM_RETRY_MS,
  type Assessment,
  type Health,
} from './liveness';
import type { Board } from './types';

// Keeps the wall board current and says, at every moment, whether it may be
// shown as current (W06, DEC-152). The rules:
//
//  - The live stream says "something changed"; the page then refetches the WHOLE
//    board. It never patches a board from an event, so a missed event is harmless
//    and a reconnect replaces everything at once.
//  - It refetches when the stream opens or reopens, on a board event, and every 60
//    seconds as a fallback. Requests are never stacked: a burst becomes one now and
//    at most one more.
//  - A board with an older `generatedAt` than the one held never replaces it, and a
//    board dated in the future is refused (it would pin the wall).
//  - An answer that cannot be read keeps the last good board and goes to Last
//    known at once. Nothing is ever blanked.
//  - It looks at the clock every second, so a board that stops refreshing for any
//    reason (the stream says it is open, a request hangs, the machine slept) turns
//    to Last known when it is too old.

/** The part of the browser's EventSource that the feed uses. */
export type StreamSource = {
  readonly readyState: number;
  onopen: ((event: Event) => void) | null;
  onerror: ((event: Event) => void) | null;
  addEventListener(type: string, listener: (event: MessageEvent) => void): void;
  close(): void;
};

export type BoardFeedOptions = {
  initialBoard: Board;
  /** The web server's clock (epoch ms) when it read `initialBoard`. */
  serverTime: number;
  fetchBoard?: (signal: AbortSignal) => Promise<FetchedBoard>;
  /** Opens the live stream, or returns null when there is none. */
  createEventSource?: () => StreamSource | null;
  /** The browser's clock in epoch ms. */
  now?: () => number;
  /** Called once when a refetch is refused because this screen is not paired. */
  onUnpaired?: () => void;
};

export type BoardFeed = { board: Board; assessment: Assessment };

/** The events that mean the board changed. `board` is what the back end sends (R06). */
export const REFRESH_EVENTS = ['board', 'board.updated'] as const;

const TICK_MS = 1_000;
const EVENT_SOURCE_CLOSED = 2;
const MINUTE_MS = 60_000;

const NO_PROBLEMS: Health = { streamDownSince: null, failingSince: null, unreadableSince: null };

/** Same words and same minute on the clock: nothing on screen would change. */
function sameAssessment(a: Assessment, b: Assessment): boolean {
  if (a.mode === 'live' || b.mode === 'live') {
    return a.mode === 'live' && b.mode === 'live' && a.streamPaused === b.streamPaused;
  }
  return (
    a.reason === b.reason &&
    a.since === b.since &&
    a.asOf === b.asOf &&
    Math.floor(Date.parse(a.now) / MINUTE_MS) === Math.floor(Date.parse(b.now) / MINUTE_MS)
  );
}

type FeedState = { board: Board; assessment: Assessment };

export function useBoardFeed(options: BoardFeedOptions): BoardFeed {
  const [state, setState] = useState<FeedState>(() => ({
    board: options.initialBoard,
    // The first render uses the web server's clock, so the server and the browser
    // draw the same thing and an old board is Last known from the first paint.
    assessment: assessBoard({
      generatedAt: options.initialBoard.generatedAt,
      nowLocal: options.serverTime,
      clockOffsetMs: 0,
      health: NO_PROBLEMS,
    }),
  }));

  // The newest options, read when something happens, so a new function identity
  // on a re-render never restarts the stream or the timers.
  const latest = useRef(options);
  useEffect(() => {
    latest.current = options;
  });

  useEffect(() => {
    const opts = () => latest.current;
    const now = () => (opts().now ?? Date.now)();

    let board = opts().initialBoard;
    // The back end's clock minus this browser's, from the last answer.
    let offset = opts().serverTime - now();
    const health: Health = { ...NO_PROBLEMS };
    let stopped = false;
    let inFlight: AbortController | null = null;
    let queued = false;
    let fetchTimer: ReturnType<typeof setTimeout> | null = null;
    let source: StreamSource | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let unpairedSignalled = false;

    function evaluate() {
      if (stopped) return;
      const assessment = assessBoard({
        generatedAt: board.generatedAt,
        nowLocal: now(),
        clockOffsetMs: offset,
        health,
      });
      const shown = board;
      setState((previous) =>
        previous.board === shown && sameAssessment(previous.assessment, assessment)
          ? previous
          : { board: shown, assessment },
      );
    }

    function accept(result: FetchedBoard) {
      if (result.serverTime !== null) offset = result.serverTime - now();
      const builtAt = Date.parse(result.board.generatedAt);
      if (!Number.isFinite(builtAt) || builtAt - (now() + offset) > MAX_FUTURE_SKEW_MS) {
        // A board from the future cannot be right, and keeping it would refuse every real one.
        health.unreadableSince ??= now();
      } else {
        health.failingSince = null;
        health.unreadableSince = null;
        // Whole-board replacement, and never by an older board.
        if (builtAt >= Date.parse(board.generatedAt)) board = result.board;
      }
      evaluate();
    }

    function fail(error: unknown) {
      const known = error instanceof BoardFetchError ? error : null;
      if (known?.kind === 'unreadable') health.unreadableSince ??= now();
      else health.failingSince ??= now();
      if (known?.kind === 'refused' && known.status !== null && REFUSED_STATUSES.includes(known.status) && !unpairedSignalled) {
        unpairedSignalled = true;
        opts().onUnpaired?.();
      }
      evaluate();
    }

    function refetch() {
      if (stopped) return;
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
        if (queued && !stopped) {
          queued = false;
          refetch();
        }
      };

      // A request that never answers is abandoned, counted as a failure, and the next poll can run.
      fetchTimer = setTimeout(() => {
        if (settled) return;
        settled = true;
        controller.abort();
        fail(new BoardFetchError('unreachable'));
        finish();
      }, FETCH_TIMEOUT_MS);

      void Promise.resolve()
        .then(() => (opts().fetchBoard ?? fetchBoardFromBff)(controller.signal))
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
      if (stopped) return;
      // Down until the server confirms it is open.
      health.streamDownSince ??= now();
      let opened: StreamSource | null = null;
      try {
        opened = opts().createEventSource?.() ?? null;
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
        // Everything that changed while it was away: refetch the whole board.
        refetch();
      };
      current.onerror = () => {
        health.streamDownSince ??= now();
        if (current.readyState === EVENT_SOURCE_CLOSED) {
          // The browser gave up on this connection (for example a refusal): open a new one shortly.
          current.close();
          if (retryTimer === null && !stopped) {
            retryTimer = setTimeout(() => {
              retryTimer = null;
              connect();
            }, STREAM_RETRY_MS);
          }
        }
        evaluate();
      };
      for (const name of REFRESH_EVENTS) current.addEventListener(name, refetch);
    }

    // The clock may differ from the one the page was drawn with.
    evaluate();
    connect();
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
  }, []);

  return state;
}
