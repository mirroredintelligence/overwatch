'use client';

import { useId } from 'react';
import type { KeyboardEvent } from 'react';
import styles from './NumberStepper.module.css';

// The reporter's number control (artboards B1, B2, D1): minus, number box, plus, and "referrals, usual range 0
// to 8" under them. The controls are 76px. An empty value is a dashed box with an en dash. The box is a real
// text field with a numeric keypad, so a number can be typed, and ArrowUp and ArrowDown step it.
// The usual range is advice, not a limit: a figure above it is allowed up to `max`, and the page asks once.
// (components/ui/NumberStepper is the smaller one the staff forms use.)

export type NumberStepperProps = {
  /** The accessible name of the number box. */
  label: string;
  value: number | null;
  onChange: (next: number | null) => void;
  /** A visible heading above the controls, like "New number of referrals". */
  title?: string;
  /** What is counted, like "referrals". */
  unit?: string;
  usualMin?: number;
  usualMax?: number;
  /** The hard upper limit (default 999). The lowest number is always 0. */
  max?: number;
  dataEl?: string;
};

const clamp = (n: number, max: number) => Math.min(max, Math.max(0, n));

export function NumberStepper({ label, value, onChange, title, unit, usualMin, usualMax, max = 999, dataEl }: NumberStepperProps) {
  const id = useId();
  const titleId = `${id}-title`;
  const rangeId = `${id}-range`;
  const range =
    unit !== undefined && usualMin !== undefined && usualMax !== undefined
      ? `${unit}, usual range ${usualMin} to ${usualMax}`
      : null;

  // From an empty box either button lands on the lowest number.
  const step = (delta: number) => onChange(value === null ? 0 : clamp(value + delta, max));

  const onType = (raw: string) => {
    if (raw === '') {
      onChange(null);
      return;
    }
    const digits = raw.replace(/\D/g, '');
    if (digits === '') return; // letters and symbols are ignored
    onChange(clamp(Number.parseInt(digits, 10), max));
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      step(1);
    } else if (event.key === 'ArrowDown') {
      event.preventDefault();
      step(-1);
    }
  };

  return (
    <div className={styles.stepper} data-el={dataEl} role="group" aria-labelledby={title !== undefined ? titleId : undefined} aria-label={title === undefined ? label : undefined}>
      {title !== undefined ? (
        <div id={titleId} className={styles.title}>
          {title}
        </div>
      ) : null}
      <div className={styles.row}>
        <button type="button" className={styles.step} aria-label="Decrease by one" onClick={() => step(-1)}>
          <span aria-hidden="true">−</span>
        </button>
        <input
          className={styles.box}
          type="text"
          inputMode="numeric"
          autoComplete="off"
          aria-label={label}
          aria-describedby={range !== null ? rangeId : undefined}
          placeholder="–"
          value={value === null ? '' : String(value)}
          data-empty={value === null ? 'true' : undefined}
          onChange={(event) => onType(event.target.value)}
          onKeyDown={onKeyDown}
        />
        <button type="button" className={styles.step} aria-label="Increase by one" onClick={() => step(1)}>
          <span aria-hidden="true">+</span>
        </button>
      </div>
      {range !== null ? (
        <p id={rangeId} className={styles.range}>
          {range}
        </p>
      ) : null}
    </div>
  );
}
