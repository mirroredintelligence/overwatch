import { useEffect, useRef, useState } from 'react';
import { BoardFetchError, fetchWallBoard, REFUSED_STATUSES, type FetchedBoard } from './client';
import {
  assessBoard,
  FETCH_TIMEOUT_MS,
  HEARTBEAT_SILENCE_MS,
  MAX_FUTURE_SKEW_MS,
  POLL_INTERVAL_MS,
  STREAM_RETRY_MS,
  type Assessment,
  type Health,
} from './liveness';
import { OWN_SCOPE, scopeKey, type WallScope } from './scope';
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
//  - Figures are kept PER SCOPE (TEN-072): each read says which board it was read under (the screen's own
//    organisation's or a network's, and the screen's version of that setting). When the scope changes the
//    figures of the old one are dropped at once and the new ones replace them, even if older; the stream is
//    opened again for the new scope, and what failed for the old scope does not count against the new. A
//    network board is never shown as last known of another scope, and a fall back to the own board is
//    reported with the flag so the screen says so.
//  - A heartbeat arrives every 15 s on an open stream. An open stream that has said nothing for
//    three beats is taken for dead (a proxy that holds the connection but passes nothing): it is
//    closed and opened again, and meanwhile the wall shows the stream as paused (KI-54). (A network's
//    stream has no named heartbeat, only comments the browser does not deliver, so it is not watched
//    this way: its 60-second read covers a silent one.)
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
  /** The scope the page read the first board under. Absent: the screen's own organisation's board. */
  initialScope?: WallScope;
  /** Opens the live stream of the scope the screen shows now, or returns null when there is none. */
  createEventSource?: (scope: WallScope) => StreamSource | null;
  /** The browser's clock in epoch ms. */
  now?: () => number;
  /** Called once when a refetch is refused because this screen is not paired. */
  onUnpaired?: () => void;
};

export type BoardFeed = {
  board: Board;
  assessment: Assessment;
  /** The board the figures were read under. */
  scope: WallScope;
  /** The name of the network the screen showed last (or shows now), kept so a fall back can say which. */
  lastNetworkName: string | null;
};

/** The events that mean the board changed. `board` is what the back end sends (R06). */
export const REFRESH_EVENTS = ['board', 'board.updated', 'board-whole'] as const;
/** The events of a network's stream: the board changed, or the screen may no longer read it (the read says which). */
export const NETWORK_REFRESH_EVENTS = ['network-board', 'scope-ended'] as const;

/** The back end's named heartbeat (KI-54): proof the stream is alive, not a change. */
export const HEARTBEAT_EVENT = 'heartbeat';

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

type FeedState = { board: Board; assessment: Assessment; scope: WallScope; lastNetworkName: string | null };

export function useBoardFeed(options: BoardFeedOptions): BoardFeed {
  const [state, setState] = useState<FeedState>(() => ({
    scope: options.initialScope ?? OWN_SCOPE,
    lastNetworkName: options.initialScope?.networkName ?? null,
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
    let scope = opts().initialScope ?? OWN_SCOPE;
    let lastNetworkName = scope.networkName;
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
    // The local clock at the last sign of life of the open stream: its opening, a heartbeat or an event.
    let lastSignal: number | null = null;

    function silenceCheck() {
      if (source === null || lastSignal === null || health.streamDownSince !== null) return;
      if (now() - lastSignal <= HEARTBEAT_SILENCE_MS) return;
      // Open, and silent for three beats: dead. Down since the last sign of life, then reconnect.
      health.streamDownSince = lastSignal + HEARTBEAT_SILENCE_MS;
      lastSignal = null;
      source.close();
      source = null;
      if (retryTimer === null && !stopped) {
        retryTimer = setTimeout(() => {
          retryTimer = null;
          connect();
        }, STREAM_RETRY_MS);
      }
    }

    function alive() {
      lastSignal = now();
      if (health.streamDownSince !== null && source !== null && source.readyState === 1) {
        health.streamDownSince = null;
        evaluate();
      }
    }

    function evaluate() {
      if (stopped) return;
      const assessment = assessBoard({
        generatedAt: board.generatedAt,
        nowLocal: now(),
        clockOffsetMs: offset,
        health,
      });
      const shown = board;
      const shownScope = scope;
      setState((previous) =>
        previous.board === shown && previous.scope === shownScope && previous.lastNetworkName === lastNetworkName && sameAssessment(previous.assessment, assessment)
          ? previous
          : { board: shown, assessment, scope: shownScope, lastNetworkName },
      );
    }

    function accept(result: FetchedBoard) {
      if (result.serverTime !== null) offset = result.serverTime - now();
      const builtAt = Date.parse(result.board.generatedAt);
      const readUnder = result.scope ?? scope;
      const changed = scopeKey(readUnder) !== scopeKey(scope);
      if (!Number.isFinite(builtAt) || builtAt - (now() + offset) > MAX_FUTURE_SKEW_MS) {
        // A board from the future cannot be right, and keeping it would refuse every real one.
        health.unreadableSince ??= now();
      } else if (changed) {
        // Another board: the figures of the old scope are dropped, never kept as the new one's last known,
        // and nothing that failed for the old scope counts against the new one.
        board = result.board;
        scope = readUnder;
        if (readUnder.networkName !== null) lastNetworkName = readUnder.networkName;
        health.failingSince = null;
        health.unreadableSince = null;
        reconnect();
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
        .then(() => (opts().fetchBoard ?? fetchWallBoard)(controller.signal))
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

    // The stream of the scope shown now is closed and the one of the new scope opened.
    function reconnect() {
      if (retryTimer !== null) clearTimeout(retryTimer);
      retryTimer = null;
      source?.close();
      source = null;
      lastSignal = null;
      health.streamDownSince = null;
      connect();
    }

    function connect() {
      if (stopped) return;
      // Down until the server confirms it is open.
      health.streamDownSince ??= now();
      let opened: StreamSource | null = null;
      try {
        opened = opts().createEventSource?.(scope) ?? null;
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
        // Only the board's own stream has a heartbeat to watch (see above).
        lastSignal = scope.boardScope === 'network' ? null : now();
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
      if (scope.boardScope === 'network') {
        // The network's own channel: a change, or "the screen may no longer read it". The read says which.
        for (const name of NETWORK_REFRESH_EVENTS) current.addEventListener(name, refetch);
      } else {
        for (const name of REFRESH_EVENTS) {
          current.addEventListener(name, () => {
            alive();
            refetch();
          });
        }
        current.addEventListener(HEARTBEAT_EVENT, alive);
      }
    }

    // The clock may differ from the one the page was drawn with.
    evaluate();
    connect();
    const poll = setInterval(refetch, POLL_INTERVAL_MS);
    const tick = setInterval(() => {
      silenceCheck();
      evaluate();
    }, TICK_MS);

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
