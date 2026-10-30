'use client';

import { type KeyboardEvent, type ReactNode, useEffect, useId, useRef } from 'react';
import styles from './Dialog.module.css';

// The shared modal shell (W14). An accessible modal: role dialog, aria-modal, named by its heading,
// focus moved in on open and back to the opener on close, Escape closes it, and Tab stays inside.
// It is a full-screen sheet at phone width. A dialog supplies its own Close and Cancel buttons.

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export type DialogProps = {
  title: string;
  sub?: string;
  dataEl?: string;
  /** An alert that needs an answer is an alertdialog (W21). Defaults to a plain dialog. */
  role?: 'dialog' | 'alertdialog';
  /**
   * Move focus to the first control on open (the default). False keeps focus on the sheet itself, which
   * a screen reader reads from its title: an alert whose first control answers a safety question must not
   * have it one keystroke from pressed (W21, DEC-854).
   */
  focusFirst?: boolean;
  onClose: () => void;
  children?: ReactNode;
};

export function Dialog({ title, sub, dataEl, role = 'dialog', focusFirst = true, onClose, children }: DialogProps) {
  const titleId = useId();
  const sheet = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // The opener is whatever had focus when the dialog appeared; it gets focus back on close.
    const opener = document.activeElement as HTMLElement | null;
    const first = focusFirst ? sheet.current?.querySelector<HTMLElement>(FOCUSABLE) : null;
    (first ?? sheet.current)?.focus();
    return () => {
      opener?.focus?.();
    };
    // Focus is placed once, when the dialog opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Escape') {
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== 'Tab' || sheet.current === null) return;
    const items = Array.from(sheet.current.querySelectorAll<HTMLElement>(FOCUSABLE));
    const first = items[0];
    const last = items[items.length - 1];
    if (first === undefined || last === undefined) return;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <div className={styles.backdrop}>
      <div
        ref={sheet}
        role={role}
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={styles.sheet}
        data-el={dataEl}
        onKeyDown={onKeyDown}
      >
        <h2 id={titleId} className={styles.title}>
          {title}
        </h2>
        {sub === undefined ? null : <p className={styles.sub}>{sub}</p>}
        {children}
      </div>
    </div>
  );
}
