'use client';

import { useId } from 'react';
import styles from './Reporter.module.css';

// A mobile number field with its own error text (W37, W38, W55). The value is held by the parent
// for the one request that needs it, and the field never echoes it into any other element.

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
    <div data-el={dataEl}>
      <label htmlFor={id} className={styles.question}>
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
        <p id={errorId} role="alert" className={styles.or}>
          {error}
        </p>
      ) : null}
    </div>
  );
}
