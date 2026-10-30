'use client';

import { useRef, type ClipboardEvent, type KeyboardEvent } from 'react';
import styles from './CodeInput.module.css';

// Six single-digit boxes read as one field (W33). A paste fills every box, Backspace in an empty
// box moves back, and the digits are never announced: each box has only its position.

const LENGTH = 6;

type Props = {
  value: string;
  onChange: (next: string) => void;
  onComplete?: (code: string) => void;
  disabled?: boolean;
  dataEl?: string;
};

export function CodeInput({ value, onChange, onComplete, disabled = false, dataEl }: Props) {
  const boxes = useRef<(HTMLInputElement | null)[]>([]);
  const digits = Array.from({ length: LENGTH }, (_, i) => value.charAt(i));

  const commit = (next: string) => {
    onChange(next);
    if (next.length === LENGTH) onComplete?.(next);
  };

  const focus = (index: number) => boxes.current[Math.min(LENGTH - 1, Math.max(0, index))]?.focus();

  const typeAt = (index: number, raw: string) => {
    const typed = raw.replace(/\D/g, '');
    if (typed === '') return;
    const next = (value.slice(0, index) + typed + value.slice(index + typed.length)).slice(0, LENGTH);
    commit(next);
    focus(Math.min(LENGTH - 1, index + typed.length));
  };

  const onKeyDown = (index: number, event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Backspace' && digits[index] === '' && index > 0) {
      event.preventDefault();
      commit(value.slice(0, index - 1));
      focus(index - 1);
    }
  };

  const onPaste = (event: ClipboardEvent<HTMLDivElement>) => {
    const pasted = event.clipboardData.getData('text').replace(/\D/g, '');
    if (pasted === '') return;
    event.preventDefault();
    const next = pasted.slice(0, LENGTH);
    commit(next);
    focus(Math.min(LENGTH - 1, next.length));
  };

  return (
    <div role="group" aria-label="6-digit code" className={styles.group} onPaste={onPaste} data-el={dataEl}>
      {digits.map((digit, index) => (
        <input
          key={index}
          ref={(node) => {
            boxes.current[index] = node;
          }}
          type="text"
          inputMode="numeric"
          autoComplete={index === 0 ? 'one-time-code' : 'off'}
          maxLength={LENGTH}
          aria-label={`Digit ${index + 1} of ${LENGTH}`}
          className={styles.box}
          value={digit}
          disabled={disabled}
          onChange={(event) => typeAt(index, event.target.value)}
          onKeyDown={(event) => onKeyDown(index, event)}
        />
      ))}
    </div>
  );
}
