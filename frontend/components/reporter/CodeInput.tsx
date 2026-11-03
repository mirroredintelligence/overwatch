'use client';

import { useId, type ChangeEvent } from 'react';
import styles from './CodeInput.module.css';

// The text code: ONE input (numeric keypad, one-time-code autofill) drawn as six boxes (R3). A paste or an
// autofilled code fills every box, Backspace deletes the last digit, and the digits are never announced:
// the field has one name and says only how many are in.

const LENGTH = 6;

type Props = {
  value: string;
  onChange: (next: string) => void;
  onComplete?: (code: string) => void;
  disabled?: boolean;
  dataEl?: string;
};

export function CodeInput({ value, onChange, onComplete, disabled = false, dataEl }: Props) {
  const countId = useId();
  const boxes = Array.from({ length: LENGTH }, (_, i) => value.charAt(i));

  const change = (event: ChangeEvent<HTMLInputElement>) => {
    const next = event.target.value.replace(/\D/g, '').slice(0, LENGTH);
    if (next === value) return;
    onChange(next);
    if (next.length === LENGTH) onComplete?.(next);
  };

  return (
    <div className={styles.group} data-el={dataEl}>
      <input
        type="text"
        inputMode="numeric"
        autoComplete="one-time-code"
        aria-label="6-digit code"
        aria-describedby={countId}
        className={styles.field}
        value={value}
        disabled={disabled}
        onChange={change}
      />
      <span id={countId} className={styles.count}>
        {`${value.length} ${value.length === 1 ? 'digit' : 'digits'} entered`}
      </span>
      <div className={styles.boxes} aria-hidden="true">
        {boxes.map((digit, index) => (
          <span
            key={index}
            className={styles.box}
            data-box=""
            data-filled={digit !== '' ? 'true' : undefined}
            data-current={index === value.length ? 'true' : undefined}
          >
            {digit}
          </span>
        ))}
      </div>
    </div>
  );
}
