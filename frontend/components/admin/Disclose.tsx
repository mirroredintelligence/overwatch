'use client';

import { useId, useRef, type ReactNode } from 'react';
import styles from './Disclose.module.css';

// One row that says its answer in a line and opens, on request, to the detail (DEC-1325 design, applied to the
// Contacts, Retention and Settings pages). The parent holds which row is open, so only one is open at a time.
// The height eases and the content settles with a short spring (Disclose.module.css; the motion tokens are zero
// under reduced motion). The closed panel is `inert`, so its fields are not in the tab order. An opened row
// brings itself fully into view, so it never opens below the fold.

export function Disclose({
  open,
  onToggle,
  title,
  hint,
  aside,
  tone,
  children,
}: {
  open: boolean;
  onToggle: () => void;
  title: ReactNode;
  /** The row's answer in a line: what is set, or what is missing. */
  hint?: ReactNode;
  /** What sits at the right of the row, before the chevron: a tag or a count. */
  aside?: ReactNode;
  tone?: 'clinical';
  children: ReactNode;
}) {
  const row = useRef<HTMLElement>(null);
  const panelId = useId();
  return (
    <section ref={row} className={styles.row} data-open={open} data-tone={tone}>
      <button
        type="button"
        className={styles.rowHead}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => {
          onToggle();
          if (!open) requestAnimationFrame(() => row.current?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' }));
        }}
      >
        <span className={styles.rowText}>
          <span className={styles.rowTitle}>{title}</span>
          {hint !== undefined ? <span className={styles.rowHint}>{hint}</span> : null}
        </span>
        <span className={styles.rowSide}>
          {aside}
          <svg className={styles.chevron} viewBox="0 0 20 20" width="18" height="18" aria-hidden="true" focusable="false">
            <path d="M5 8l5 5 5-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </span>
      </button>
      <div id={panelId} className={styles.panel} data-open={open} inert={!open}>
        <div className={styles.panelInner}>
          <div className={styles.panelBody}>{children}</div>
        </div>
      </div>
    </section>
  );
}
