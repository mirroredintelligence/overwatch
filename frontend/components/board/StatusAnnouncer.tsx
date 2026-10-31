'use client';

import { useState } from 'react';
import { STATUS_LABELS } from '@/components/ui/StatusBadge';
import type { Board } from '@/lib/board/types';
import styles from './Board.module.css';

// A polite live region for status changes on the wall (KI-56, design-system 5.4 item 4): a person who cannot
// see the tiles hears that a service changed. Each change is one sentence, said once, in the order of the
// board; the first board, a change of figure only, a service that appeared and a board shown as last known
// say nothing (a figure of old data is never announced as news). The region is always there, so the
// announcement is made when its text changes.

function announcement(before: Board, now: Board): string {
  const was = new Map(before.entries.map((entry) => [entry.serviceId, entry.status]));
  return now.entries
    .filter((entry) => was.has(entry.serviceId) && was.get(entry.serviceId) !== entry.status)
    .map((entry) => `${entry.name} is now ${STATUS_LABELS[entry.status]}.`)
    .join(' ');
}

export function StatusAnnouncer({ board, lastKnown = false }: { board: Board; lastKnown?: boolean }) {
  const [state, setState] = useState<{ board: Board; text: string }>({ board, text: '' });
  if (state.board !== board) setState({ board, text: lastKnown ? '' : announcement(state.board, board) });
  return (
    <div role="status" aria-live="polite" aria-atomic="true" className={styles.visuallyHidden}>
      {state.text}
    </div>
  );
}
