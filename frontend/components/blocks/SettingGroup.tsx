'use client';

import type { ReactNode } from 'react';
import { Disclose } from '@/components/admin/Disclose';
import styles from './SettingGroup.module.css';

// A group of settings: a header that says what the group is, what a change to it needs, how many settings it
// holds and how many are changed in the draft. The parent holds which group is open, so one is open at a time.
// The open and close transition is the shared Disclose.

export function SettingGroup({
  open,
  onToggle,
  title,
  about,
  count,
  changed = 0,
  children,
}: {
  open: boolean;
  onToggle: () => void;
  title: string;
  /** What a change to this group needs. */
  about?: string;
  /** The count in words: "3 settings", or "2 match" while finding. */
  count: string;
  /** How many settings in the group differ from what is in force. Nothing is shown at zero. */
  changed?: number;
  children: ReactNode;
}) {
  return (
    <Disclose
      open={open}
      onToggle={onToggle}
      title={title}
      hint={about}
      aside={
        <>
          {changed > 0 ? (
            <span className={styles.badge}>
              <span aria-hidden="true">● </span>
              {changed} changed
            </span>
          ) : null}
          <span className={styles.count}>{count}</span>
        </>
      }
    >
      <div className={styles.items}>{children}</div>
    </Disclose>
  );
}
