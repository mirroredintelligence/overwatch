'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { bffRequest, type BffResult } from '@/lib/bff/browser';
import { newIdempotencyKey } from '@/lib/lead/browser';

// The administration pages' calls to their BFF routes (TEN-076). A read says loading, ok or failed, with the
// status of a failure so a page can say the right words for a 404 or a 403; a write is one call with one
// idempotency key per submit (DEC-653): a retry of the same submit sends the same key, so it is a replay at
// the back end and not a second change, and an edit of the form makes a new one (a key is for one body).

export type Read<T> = { status: 'loading' } | { status: 'ok'; data: T } | { status: 'failed'; http: number };

export function useAdminRead<T>(path: string | null): { state: Read<T>; reload: () => void } {
  const [state, setState] = useState<Read<T>>({ status: 'loading' });
  const [round, setRound] = useState(0);
  useEffect(() => {
    if (path === null) return;
    let current = true;
    void bffRequest<T>(path).then((result) => {
      if (!current) return;
      setState(result.ok ? { status: 'ok', data: result.data } : { status: 'failed', http: result.status });
    });
    return () => {
      current = false;
    };
  }, [path, round]);
  const reload = useCallback(() => setRound((n) => n + 1), []);
  return { state, reload };
}

/** One call to a write route, with the key of this submit. */
export function adminSend<T>(method: 'POST' | 'PUT' | 'DELETE', path: string, body: unknown, key: string): Promise<BffResult<T>> {
  return bffRequest<T>(path, { method, body, idempotencyKey: key });
}

/** The idempotency key of the submit in progress: the same until `fresh()` (after an edit or a success). */
export function useSubmitKey(): { key: () => string; fresh: () => void } {
  const held = useRef<string | null>(null);
  const key = useCallback(() => {
    held.current ??= newIdempotencyKey();
    return held.current;
  }, []);
  const fresh = useCallback(() => {
    held.current = null;
  }, []);
  return { key, fresh };
}
