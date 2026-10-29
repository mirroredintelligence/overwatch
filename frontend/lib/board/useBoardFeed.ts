import { useEffect } from 'react';
import type { Assessment } from './liveness';
import type { FetchedBoard } from './client';
import type { Board } from './types';

export type StreamSource = {
  readonly readyState: number;
  onopen: ((event: Event) => void) | null;
  onerror: ((event: Event) => void) | null;
  addEventListener(type: string, listener: (event: MessageEvent) => void): void;
  close(): void;
};

export type BoardFeedOptions = {
  initialBoard: Board;
  serverTime: number;
  fetchBoard?: (signal: AbortSignal) => Promise<FetchedBoard>;
  createEventSource?: () => StreamSource | null;
  now?: () => number;
  onUnpaired?: () => void;
};

export type BoardFeed = { board: Board; assessment: Assessment };

export function useBoardFeed(options: BoardFeedOptions): BoardFeed {
  const { createEventSource } = options;
  useEffect(() => {
    const stream = createEventSource?.();
    return () => stream?.close();
  }, [createEventSource]);
  return { board: options.initialBoard, assessment: { mode: 'live', streamPaused: false } };
}
