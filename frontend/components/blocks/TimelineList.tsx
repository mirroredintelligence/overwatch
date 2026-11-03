import type { ReactNode } from 'react';
import styles from './TimelineList.module.css';

// A list of things in time (audit chain O6, access log A7, versions). Each entry: title, one detail line and
// the time. `line` draws the chain's rail down the left with a dot per entry (O6); without it the dot sits
// inline (A7). Tone: normal (primary dot), attention (amber), past (pale). The dot is decoration.

export type TimelineItem = {
  id: string;
  title: ReactNode;
  detail?: ReactNode;
  time: string;
  at?: string;
  tone?: 'normal' | 'attention' | 'past';
};

export function TimelineList({ label, items, line }: { label: string; items: readonly TimelineItem[]; line?: boolean }) {
  return (
    <div className={styles.wrap} data-line={line ? 'true' : undefined}>
      {line ? <span className={styles.rail} aria-hidden="true" /> : null}
      <ul className={styles.list} aria-label={label}>
        {items.map((item) => (
          <li key={item.id} className={styles.item} data-tone={item.tone ?? 'normal'}>
            <span className={styles.dot} data-dot aria-hidden="true" />
            <div className={styles.text}>
              <div className={styles.title}>{item.title}</div>
              {item.detail ? <div className={styles.detail}>{item.detail}</div> : null}
            </div>
            <time className={styles.time} dateTime={item.at}>
              {item.time}
            </time>
          </li>
        ))}
      </ul>
    </div>
  );
}
