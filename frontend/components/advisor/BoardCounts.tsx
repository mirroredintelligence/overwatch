'use client';

import { useEffect, useState } from 'react';
import { StatusBadge, type StatusCode } from '@/components/ui/StatusBadge';
import { fetchBoardFromBff } from '@/lib/board/client';
import type { Board } from '@/lib/board/types';
import styles from './BoardCounts.module.css';

// The five counts on the advisor home (W10), from the same board the wall shows: GET /api/bff/board.
// Each count has its status word and shape (StatusBadge), so no colour is needed to read it.

const COUNTED: readonly { status: StatusCode; key: string }[] = [
  { status: 'accepting', key: 'ACCEPTING' },
  { status: 'limited', key: 'LIMITED' },
  { status: 'not-accepting', key: 'NOT-ACCEPTING' },
  { status: 'over-capacity', key: 'OVER-CAPACITY' },
  { status: 'not-updated', key: 'NOT-UPDATED' },
];

export function countsOf(board: Board): Record<StatusCode, number> {
  const counts: Record<StatusCode, number> = {
    accepting: 0,
    limited: 0,
    'not-accepting': 0,
    'over-capacity': 0,
    'not-updated': 0,
    'out-of-hours': 0,
    'last-known': 0,
  };
  for (const entry of board.entries) counts[entry.status] += 1;
  return counts;
}

type State = { kind: 'loading' } | { kind: 'ready'; counts: Record<StatusCode, number> } | { kind: 'failed' };

export function BoardCounts() {
  const [state, setState] = useState<State>({ kind: 'loading' });

  useEffect(() => {
    const controller = new AbortController();
    fetchBoardFromBff(controller.signal)
      .then(({ board }) => setState({ kind: 'ready', counts: countsOf(board) }))
      .catch(() => {
        if (!controller.signal.aborted) setState({ kind: 'failed' });
      });
    return () => controller.abort();
  }, []);

  if (state.kind === 'loading') return <p>Loading the board.</p>;
  if (state.kind === 'failed') return <p>The board could not be read. Open the wall board view to try again.</p>;

  return (
    <ul className={styles.counts}>
      {COUNTED.map(({ status, key }) => (
        <li key={status} className={styles.row}>
          <StatusBadge status={status} />
          <span className={styles.count} data-el={`ADV-HOME-COUNT-${key}`}>
            {state.counts[status]}
          </span>
        </li>
      ))}
    </ul>
  );
}
