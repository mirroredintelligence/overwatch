import type { BoardStatus } from '@/lib/board/types';
import { StatusChip } from './StatusChip';
import styles from './Legend.module.css';

// The key under the board (artboards BoardNormal and WallBoard). Each meaning is the same chip the
// tiles use, with the same shape and word, so the key and a tile never disagree and it is never colour alone.
const ITEMS: { status: BoardStatus; text: string }[] = [
  { status: 'accepting', text: 'Accepting' },
  { status: 'limited', text: 'Limited: phone to confirm' },
  { status: 'not-accepting', text: 'Not accepting' },
  { status: 'over-capacity', text: 'Over capacity' },
  { status: 'not-updated', text: 'Not updated: treat as unknown, phone' },
  { status: 'out-of-hours', text: 'Out of hours: closed, not counted' },
];

export function Legend() {
  return (
    <ul className={styles.legend} aria-label="Status key">
      {ITEMS.map(({ status, text }) => (
        <li key={status} className={styles.item}>
          <StatusChip status={status} label={text} />
        </li>
      ))}
    </ul>
  );
}
