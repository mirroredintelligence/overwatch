import type { FlagItem } from '@/lib/lead/flags';
import styles from './FlagList.module.css';

// The master list of flagged reports: a ul of buttons, one per flag, with the service and the reason in words.
// The open flag has aria-current and a border; on a phone a tap on a row opens the flag as a step of its own.

export type FlagListProps = {
  items: readonly FlagItem[];
  /** The flag open beside the list, or null. */
  currentId: string | null;
  onOpen: (id: string) => void;
};

export function FlagList({ items, currentId, onOpen }: FlagListProps) {
  return (
    <ul className={styles.list} aria-label="Flagged reports">
      {items.map((item) => (
        <li key={item.id}>
          <button
            type="button"
            className={styles.row}
            aria-current={item.id === currentId ? 'true' : undefined}
            onClick={() => onOpen(item.id)}
            data-el="LEAD-FLAG-ROW-BTN"
          >
            <span className={styles.name}>{item.serviceName}</span>
            <span className={styles.reason}>{item.summary}</span>
            <svg className={styles.chevron} viewBox="0 0 20 20" aria-hidden="true" focusable="false">
              <path d="M8 5l5 5-5 5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        </li>
      ))}
    </ul>
  );
}
