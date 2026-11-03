import type { ReactNode } from 'react';
import { Disclose } from '@/components/admin/Disclose';
import styles from './DisclosureRow.module.css';

// A closed row at the foot of the overview (the board's "Criteria to review", "Declined despite showing
// capacity"): the title and its answer in one line, and one panel that opens on request. The parent holds which
// row is open, so only one is open at a time. The row, its panel and its motion are the shared Disclose.

export type DisclosureRowProps = {
  open: boolean;
  onToggle: () => void;
  title: string;
  /** The answer in a few words: "2 services, the soonest in 7 days". */
  hint: string;
  children: ReactNode;
};

export function DisclosureRow({ open, onToggle, title, hint, children }: DisclosureRowProps) {
  return (
    <div className={styles.wrap}>
      <Disclose
        open={open}
        onToggle={onToggle}
        title={
          <span className={styles.line}>
            {title}
            <span className={styles.hint}>{` · ${hint}`}</span>
          </span>
        }
      >
        {children}
      </Disclose>
    </div>
  );
}
