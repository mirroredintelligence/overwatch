'use client';

import { useId } from 'react';
import styles from './MobileNumberField.module.css';

// A mobile number field with its own error text (W37, W38, W55). The value is held by the parent
// for the one request that needs it, and the field never echoes it into any other element.
// Drawn as artboard B7 (3): a bold label over a 54px field with a dark 2px border. An error is a warning
// shape plus words, never colour alone.

export const MOBILE_ERROR = 'Enter a UK mobile number, like 07700 900123';

type Props = {
  label: string;
  value: string;
  onChange: (next: string) => void;
  error?: string | null;
  required?: boolean;
  dataEl?: string;
};

export function MobileNumberField({ label, value, onChange, error = null, required = false, dataEl }: Props) {
  const id = useId();
  const errorId = `${id}-error`;
  return (
    <div className={styles.field} data-el={dataEl} data-invalid={error !== null ? 'true' : undefined}>
      <label htmlFor={id} className={styles.label}>
        {label}
      </label>
      {required ? <span className={styles.hint}> Required</span> : null}
      <input
        id={id}
        type="tel"
        inputMode="tel"
        autoComplete="tel"
        value={value}
        required={required}
        aria-invalid={error !== null ? 'true' : undefined}
        aria-describedby={error !== null ? errorId : undefined}
        onChange={(event) => onChange(event.target.value)}
        className={styles.input}
      />
      {error !== null ? (
        <p id={errorId} role="alert" className={styles.error}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
            <path d="M12 3l10 18H2z" />
            <path d="M12 10v5M12 18.2h.01" />
          </svg>
          {error}
        </p>
      ) : null}
    </div>
  );
}
