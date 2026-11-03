'use client';

import { type ReactNode, useEffect, useRef } from 'react';
import { Dialog } from '@/components/ui/Dialog';
import styles from './ConfirmDialog.module.css';

// A confirmation that names the act and the thing in its title and says the consequence in its body (W21).
// It is an alertdialog. The safe choice (cancel) has initial focus and is drawn the same size as the
// destructive one, so neither is easier to hit. The destructive button is first in reading order, as on the
// board; Escape is the safe choice too. Build on the shared Dialog shell for focus trap and focus return.

export type ConfirmDialogProps = {
  /** The act and the thing: "Remove access for ···0377?" */
  title: string;
  /** The consequence, in plain words. */
  children: ReactNode;
  /** The destructive button, naming the act: "Remove access". */
  confirmLabel: string;
  /** The safe button, naming what stays: "Keep access". */
  cancelLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
  /** Disables the destructive button only, so a second press does nothing. */
  busy?: boolean;
  /** A failed attempt, said in words. */
  error?: string;
  dataEl?: string;
};

export function ConfirmDialog({
  title,
  children,
  confirmLabel,
  cancelLabel,
  onConfirm,
  onCancel,
  busy = false,
  error,
  dataEl,
}: ConfirmDialogProps) {
  const safe = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    // The shell places focus on its sheet after this effect, so move to the safe button once it has.
    queueMicrotask(() => safe.current?.focus());
  }, []);

  return (
    <Dialog title={title} role="alertdialog" focusFirst={false} dataEl={dataEl} onClose={onCancel}>
      <div className={styles.icon} aria-hidden="true">
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 3l10 18H2z" />
          <path d="M12 10v5M12 18h.01" />
        </svg>
      </div>
      <div className={styles.body}>{children}</div>
      {error === undefined ? null : (
        <p role="alert" className={styles.error}>
          {error}
        </p>
      )}
      <div className={styles.actions}>
        <button
          type="button"
          className={styles.button}
          data-choice="danger"
          disabled={busy}
          aria-busy={busy ? 'true' : undefined}
          onClick={onConfirm}
        >
          {confirmLabel}
        </button>
        <button ref={safe} type="button" className={styles.button} data-choice="safe" onClick={onCancel}>
          {cancelLabel}
        </button>
      </div>
    </Dialog>
  );
}
