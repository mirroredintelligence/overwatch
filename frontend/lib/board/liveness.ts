// How the wall decides whether a board may be shown as current (W06, DEC-152).
// Pure functions of times, so every rule is tested with plain numbers.

export const POLL_INTERVAL_MS = 60_000;
export const STREAM_GAP_MS = 10_000;
export const STREAM_RETRY_MS = 5_000;
export const STALE_AFTER_MS = 180_000;
export const MAX_FUTURE_SKEW_MS = 60_000;

export type LastKnownReason = 'offline' | 'unreadable' | 'old';

export type Health = {
  /** Local clock (ms) when the live stream last stopped being open, or null while it is open. */
  streamDownSince: number | null;
  /** Local clock (ms) of the first failed refetch since the last good one, or null. */
  failingSince: number | null;
  /** Local clock (ms) of the first answer that could not be read since the last good one, or null. */
  unreadableSince: number | null;
};

export type Assessment =
  | { mode: 'live'; streamPaused: boolean }
  | {
      mode: 'last-known';
      reason: LastKnownReason;
      /** ISO instant: the first failure, or the board's own time when there was none. */
      since: string;
      /** ISO instant: when the board shown was built (the back end's clock). */
      asOf: string;
      /** ISO instant: the best estimate of the back end's clock now. */
      now: string;
      ageMs: number;
    };

export type AssessInput = {
  generatedAt: string;
  nowLocal: number;
  /** Back end's clock minus this browser's clock, from the last answer. */
  clockOffsetMs: number;
  health: Health;
};

export function assessBoard(input: AssessInput): Assessment {
  void input;
  return { mode: 'live', streamPaused: false };
}
