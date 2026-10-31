'use client';

import { useEffect, useState } from 'react';
import { bffRequest } from '@/lib/reporter/browser';

// The browser's calls to the practitioner BFF. They go through the same helper as the reporter app's, so
// every write carries the CSRF token of the session. A 401 is the end of the session: the PIN screen.
// Nothing here keeps an address, a contact or a position: a value lives in the component that asked.

export type Loaded<T> = { kind: 'loading' } | { kind: 'ready'; value: T } | { kind: 'failed' } | { kind: 'ended' };

/** Reads `path` once, and again when `reload` changes, with the answer checked by `parse`. */
export function useBffRead<T>(path: string, parse: (body: unknown) => T | null, reload = 0): Loaded<T> {
  const [state, setState] = useState<Loaded<T>>({ kind: 'loading' });
  useEffect(() => {
    let live = true;
    void bffRequest(path).then((reply) => {
      if (!live) return;
      if (reply.status === 401) return setState({ kind: 'ended' });
      const value = reply.status === 200 ? parse(reply.body) : null;
      setState(value === null ? { kind: 'failed' } : { kind: 'ready', value });
    });
    return () => {
      live = false;
    };
    // `parse` is a module-level function of the caller: it is not a reason to read again.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, reload]);
  return state;
}

/** "m:ss" for a count of seconds, never negative. */
export function countdown(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
}

/** Seconds left until `instant`, counted from `now` (a number of milliseconds). */
export function secondsLeft(instant: string, now: number): number {
  return Math.max(0, Math.ceil((Date.parse(instant) - now) / 1000));
}
