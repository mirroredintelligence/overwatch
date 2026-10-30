'use client';

import { useState } from 'react';
import styles from './PinPad.module.css';

// The keypad for a 6-digit PIN (W34, reused by W35 and W37). Real buttons, each named. The digits
// are never written to the page: the live region counts them, and the PIN goes to onComplete once,
// then the pad clears itself. The PIN is held in component state only, never in browser storage.

const KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'];

type Props = {
  length?: number;
  label: string;
  onComplete: (pin: string) => void;
  /** The prefix of the stable data-el ids, for example ONB or REP-APP. */
  dataEl?: string;
};

export function PinPad({ length = 6, label, onComplete, dataEl = 'PIN' }: Props) {
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
      <p className={styles.label}>{label}</p>
      <p role="status" aria-live="polite" className={styles.count}>
        {`${digits.length} of ${length} digits entered`}
      </p>
      <div className={styles.dots} data-el={`${dataEl}-DOTS`} aria-hidden="true">
        {Array.from({ length }, (_, i) => (
          <span key={i} className={i < digits.length ? styles.filled : styles.empty} />
        ))}
      </div>
      <div role="group" aria-label={label} className={styles.keys}>
        {KEYS.map((digit, index) => (
          <button
            key={digit}
            type="button"
            className={styles.key}
            aria-label={digit}
            data-el={`${dataEl}-PIN-KEY-${index === 9 ? 0 : index + 1}`}
            onClick={() => press(digit)}
          >
            {digit}
          </button>
        ))}
        <button type="button" className={`${styles.key} ${styles.delete}`} aria-label="Delete" onClick={remove}>
          Delete
        </button>
      </div>
    </div>
  );
}
