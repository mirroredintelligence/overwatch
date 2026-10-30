'use client';

import { useEffect, useState } from 'react';
import { bffGet } from '@/lib/bff/client';

// One read from the BFF for a check step. `loading` until the answer comes; `failed` when it does not.
// The parser is a module-level function, so the read runs once per path.

export type ReadState<T> = { status: 'loading' } | { status: 'ok'; data: T } | { status: 'failed' };

export function useRead<T>(path: string, parse: (value: unknown) => T): ReadState<T> {
  const [state, setState] = useState<ReadState<T>>({ status: 'loading' });
  useEffect(() => {
    let current = true;
    void (async () => {
      const result = await bffGet(path, parse);
      if (!current) return;
      setState(result.ok ? { status: 'ok', data: result.data } : { status: 'failed' });
    })();
    return () => {
      current = false;
    };
  }, [path, parse]);
  return state;
}
