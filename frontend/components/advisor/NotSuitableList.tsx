'use client';

import { useState } from 'react';
import type { NotSuitableView } from '@/lib/advisor/options';
import styles from './NotSuitableList.module.css';

// The services that were excluded and why (W13). Closed by default; the disclosure says how many.

const LIST_ID = 'not-suitable-list';

export function NotSuitableList({ items }: { items: NotSuitableView[] }) {
  const [open, setOpen] = useState(false);
  const count = items.length;
  const label = count === 1 ? '1 service not suitable, and why' : `${count} services not suitable, and why`;

  return (
    <div className={styles.wrap}>
      <button
        type="button"
        className={styles.toggle}
        aria-expanded={open}
        aria-controls={open ? LIST_ID : undefined}
        onClick={() => setOpen((current) => !current)}
      >
        {label}
      </button>
      {open ? (
        <ul id={LIST_ID} className={styles.list}>
          {items.map((item) => (
            <li key={item.serviceId}>{`${item.name}: ${item.reason}`}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
