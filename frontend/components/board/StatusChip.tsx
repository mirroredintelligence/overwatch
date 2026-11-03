import type { BoardStatus } from '@/lib/board/types';
import styles from './StatusChip.module.css';

// The six states of a service as a shape plus a word, never colour alone (advisor-clinical-wall.md
// section 2, "Status language"; artboards BoardNormal, BoardQuiet, BoardDown). Used by the tile, the
// key and every screen that draws a service's state. "Last known" is not a state: it is the dashed
// pill below, laid over whichever state the tile has.

export const CHIP_WORDS: Record<BoardStatus, string> = {
  accepting: 'Accepting',
  limited: 'Limited',
  'not-accepting': 'Not accepting',
  'over-capacity': 'Over capacity',
  'not-updated': 'Not updated',
  'out-of-hours': 'Out of hours',
};

export type ChipShape = 'circle' | 'half-circle' | 'square' | 'triangle' | 'dashed-ring' | 'crescent';

export const CHIP_SHAPES: Record<BoardStatus, ChipShape> = {
  accepting: 'circle',
  limited: 'half-circle',
  'not-accepting': 'square',
  'over-capacity': 'triangle',
  'not-updated': 'dashed-ring',
  'out-of-hours': 'crescent',
};

const VARIANT: Record<BoardStatus, string> = {
  accepting: styles.accepting,
  limited: styles.limited,
  'not-accepting': styles.notAccepting,
  'over-capacity': styles.overCapacity,
  'not-updated': styles.notUpdated,
  'out-of-hours': styles.outOfHours,
};

// The shapes draw in currentColor, so they follow the word's colour.
function Shape({ shape }: { shape: ChipShape }) {
  const common = { viewBox: '0 0 16 16', 'aria-hidden': true, focusable: false, className: styles.shape } as const;
  switch (shape) {
    case 'circle':
      return (
        <svg {...common}>
          <circle cx="8" cy="8" r="7" fill="currentColor" />
        </svg>
      );
    case 'half-circle':
      return (
        <svg {...common}>
          <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeWidth="2" />
          <path d="M8 2a6 6 0 0 0 0 12z" fill="currentColor" />
        </svg>
      );
    case 'square':
      return (
        <svg {...common}>
          <rect x="2" y="2" width="12" height="12" rx="2" fill="currentColor" />
        </svg>
      );
    case 'triangle':
      return (
        <svg {...common}>
          <path d="M8 1.5L15 14H1z" fill="currentColor" stroke="currentColor" strokeWidth="1" strokeLinejoin="round" />
        </svg>
      );
    case 'dashed-ring':
      return (
        <svg {...common}>
          <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeWidth="2" strokeDasharray="3 2.4" />
        </svg>
      );
    case 'crescent':
      return (
        <svg {...common}>
          <path d="M13.2 10.4A6 6 0 0 1 5.6 2.8a6 6 0 1 0 7.6 7.6z" fill="currentColor" />
        </svg>
      );
  }
}

export function StatusChip({
  status,
  size = 'md',
  label,
}: {
  status: BoardStatus;
  size?: 'md' | 'lg';
  /** A longer wording of the same state ("Limited: phone to confirm"), for the key. The state is still the one named. */
  label?: string;
}) {
  return (
    <span
      className={`${styles.chip} ${VARIANT[status]} ${size === 'lg' ? styles.lg : ''}`}
      data-status={status}
      data-shape={CHIP_SHAPES[status]}
      data-size={size}
    >
      <Shape shape={CHIP_SHAPES[status]} />
      <span>{label ?? CHIP_WORDS[status]}</span>
    </span>
  );
}

/** The overlay for a figure that cannot be refreshed: a dashed pill with the words. It is never a status. */
export function LastKnownPill() {
  return (
    <span className={styles.lastKnown} data-overlay="last-known" data-shape="dashed-ring">
      Last known
    </span>
  );
}
