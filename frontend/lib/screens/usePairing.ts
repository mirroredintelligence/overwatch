'use client';

import { useEffect, useRef, useState } from 'react';
import type { PairingStatus, StartedPairing } from './client';
import { formatCode } from './model';

// The wall display's side of pairing. On opening it tries its own session first (a paired screen
// that was switched off comes back without anyone); with none it asks for a code, shows it, and asks
// every three seconds whether a lead has connected it. A code that runs out is replaced at once, with
// no one touching the screen: the back end gives the device token for ten minutes only (DEC-224 item
// 20), so the screen must keep asking from the moment it shows a code.

export const POLL_INTERVAL_MS = 3000;
export const RETRY_UNAVAILABLE_MS = 10_000;
// [ASSUMED] How long to wait, when the back end throttles and does not say how long.
export const RETRY_THROTTLED_MS = 60_000;

export type PairingApi = {
  renew: (signal?: AbortSignal) => Promise<void>;
  start: (signal?: AbortSignal) => Promise<StartedPairing>;
  poll: (pairingId: string, signal?: AbortSignal) => Promise<PairingStatus>;
};

/** `disconnected` is present (true) only on a screen a lead disconnected: its renewal was refused. */
export type PairingView = (
  | { kind: 'connecting' }
  | { kind: 'code'; code: string; expiresAt: string }
  | { kind: 'throttled' }
  | { kind: 'unavailable' }
) & { disconnected?: true };

function kindOf(error: unknown): string | null {
  return typeof error === 'object' && error !== null && 'kind' in error ? String((error as { kind: unknown }).kind) : null;
}

function waitOf(error: unknown): number | null {
  const wait = typeof error === 'object' && error !== null && 'retryAfterMs' in error ? (error as { retryAfterMs: unknown }).retryAfterMs : null;
  return typeof wait === 'number' && wait > 0 ? wait : null;
}

function wasDisconnected(error: unknown): boolean {
  return typeof error === 'object' && error !== null && 'disconnected' in error && (error as { disconnected: unknown }).disconnected === true;
}

export function usePairing({ api, onPaired }: { api: PairingApi; onPaired: () => void }): PairingView {
  const [shown, setView] = useState<PairingView>({ kind: 'connecting' });
  const [disconnected, setDisconnected] = useState(false);
  const view: PairingView = disconnected ? { ...shown, disconnected: true } : shown;
  const done = useRef(onPaired);
  useEffect(() => {
    done.current = onPaired;
  });

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const sleep = (ms: number) =>
      new Promise<void>((resolve) => {
        timer = setTimeout(resolve, ms);
        signal.addEventListener('abort', () => {
          clearTimeout(timer);
          resolve();
        }, { once: true });
      });

    async function run() {
      let phase: 'renew' | 'start' | 'poll' = 'renew';
      let pairingId = '';
      // One request at a time, always: the next is not asked until the last has answered.
      while (!signal.aborted) {
        if (phase === 'renew') {
          try {
            await api.renew(signal);
            if (!signal.aborted) done.current();
            return;
          } catch (error) {
            if (signal.aborted) return;
            if (kindOf(error) === 'not-found') {
              if (wasDisconnected(error)) setDisconnected(true);
              phase = 'start';
            } else {
              setView({ kind: 'connecting' });
              await sleep(RETRY_UNAVAILABLE_MS);
            }
          }
        } else if (phase === 'start') {
          try {
            const started = await api.start(signal);
            if (signal.aborted) return;
            pairingId = started.pairingId;
            setView({ kind: 'code', code: formatCode(started.code), expiresAt: started.expiresAt });
            phase = 'poll';
          } catch (error) {
            if (signal.aborted) return;
            if (kindOf(error) === 'throttled') {
              setView({ kind: 'throttled' });
              await sleep(waitOf(error) ?? RETRY_THROTTLED_MS);
            } else {
              setView({ kind: 'unavailable' });
              await sleep(RETRY_UNAVAILABLE_MS);
            }
          }
        } else {
          await sleep(POLL_INTERVAL_MS);
          if (signal.aborted) return;
          try {
            const status = await api.poll(pairingId, signal);
            if (signal.aborted) return;
            if (status === 'paired') {
              done.current();
              return;
            }
            if (status === 'expired') phase = 'start';
            else if (status === 'connecting') phase = 'renew';
          } catch (error) {
            if (signal.aborted) return;
            // The back end no longer knows this pairing: a new code. Anything else (a throttle, an
            // outage) leaves the code on screen and asks again in three seconds.
            if (kindOf(error) === 'not-found') phase = 'start';
          }
        }
      }
    }

    void run();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [api]);

  return view;
}
