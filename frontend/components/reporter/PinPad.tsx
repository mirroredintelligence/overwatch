'use client';

import { useState } from 'react';
import styles from './PinPad.module.css';

// The keypad for a 6-digit PIN (W34, reused by W35 and W37). Real buttons, each named. The digits
// are never written to the page: the live region counts them, and the PIN goes to onComplete once,
// then the pad clears itself. The PIN is held in component state only, never in browser storage.
// There is no Continue key: the sixth digit completes the PIN.

const KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'];

type Props = {
  length?: number;
  label: string;
  /** Show the label above the dots. A page that already shows it as its heading passes false. */
  showLabel?: boolean;
  onComplete: (pin: string) => void;
  /** The prefix of the stable data-el ids, for example ONB or REP-APP. */
  dataEl?: string;
};

export function PinPad({ length = 6, label, showLabel = true, onComplete, dataEl = 'PIN' }: Props) {
  const [digits, setDigits] = useState('');

  const press = (digit: string) => {
    if (digits.length >= length) return;
    const next = digits + digit;
    if (next.length === length) {
      setDigits('');
      onComplete(next);
      return;
    }
    setDigits(next);
  };

  const remove = () => setDigits((current) => current.slice(0, -1));

  return (
    <div className={styles.pad}>
      {showLabel ? <p className={styles.label}>{label}</p> : null}
      <p role="status" aria-live="polite" className={styles.count}>
        {`${digits.length} of ${length} digits entered`}
      </p>
      <div className={styles.dots} data-el={`${dataEl}-DOTS`} aria-hidden="true">
        {Array.from({ length }, (_, i) => (
          <span key={i} className={styles.dot} data-filled={i < digits.length ? 'true' : 'false'} />
        ))}
      </div>
      <div role="group" aria-label={label} className={styles.keys}>
        {KEYS.slice(0, 9).map((digit, index) => (
          <button
            key={digit}
            type="button"
            className={styles.key}
            aria-label={digit}
            data-el={`${dataEl}-PIN-KEY-${index + 1}`}
            onClick={() => press(digit)}
          >
            {digit}
          </button>
        ))}
        <span aria-hidden="true" />
        <button
          type="button"
          className={styles.key}
          aria-label="0"
          data-el={`${dataEl}-PIN-KEY-0`}
          onClick={() => press('0')}
        >
          0
        </button>
        <button type="button" className={`${styles.key} ${styles.delete}`} aria-label="Delete" onClick={remove}>
          <svg
            width="30"
            height="30"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M21 5H9l-6 7 6 7h12zM15 9l-4 6M11 9l4 6" />
          </svg>
        </button>
      </div>
    </div>
  );
}
