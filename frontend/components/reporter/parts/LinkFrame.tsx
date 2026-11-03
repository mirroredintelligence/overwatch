import type { ReactNode } from 'react';
import styles from './LinkFrame.module.css';

// The frame of a public link page (artboards B3, B4): a light top bar with the mark and, unless the page
// leaves it out, a "No login needed" tag, over a centred column up to 480px. The frame draws no <main> and
// no heading: the page keeps its own.

export function LinkFrame({ children, noLoginTag = true }: { children: ReactNode; noLoginTag?: boolean }) {
  return (
    <div className={styles.frame}>
      <header className={styles.bar}>
        <span className={styles.brand}>
          <svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true" focusable="false">
            <circle cx="13" cy="13" r="10" fill="none" stroke="currentColor" strokeWidth="2.4" />
            <circle cx="13" cy="13" r="4.2" fill="var(--c-primary)" />
            <path d="M3 13h20" stroke="currentColor" strokeWidth="2.4" />
          </svg>
          Overwatch
        </span>
        {noLoginTag ? <span className={styles.tag}>No login needed</span> : null}
      </header>
      <div className={styles.column}>{children}</div>
    </div>
  );
}
