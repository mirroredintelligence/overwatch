import { useId } from 'react';
import styles from './NumberStepper.module.css';

export type NumberStepperProps = {
  label: string;
  value: number | null;
  min: number;
  max: number;
  onChange: (next: number | null) => void;
  hint?: string;
  placeholder?: string;
  dataEl?: string;
};

const clamp = (n: number, min: number, max: number) => Math.min(max, Math.max(min, n));

export function NumberStepper({
  label,
  value,
  min,
  max,
  onChange,
  hint,
  placeholder = '–',
  dataEl,
}: NumberStepperProps) {
  const id = useId();
  const hintId = `${id}-hint`;

  const step = (delta: number) => {
    // From an empty field either button lands on the lowest allowed value.
    onChange(value === null ? min : clamp(value + delta, min, max));
  };

  const onType = (raw: string) => {
    if (raw === '') {
      onChange(null);
      return;
    }
    const digits = raw.replace(/\D/g, '');
    if (digits === '') return; // letters and symbols are ignored
    onChange(clamp(Number.parseInt(digits, 10), min, max));
  };

  return (
    <div className={styles.stepper} data-el={dataEl}>
      <label className={styles.label} htmlFor={id}>
        {label}
      </label>
      <div className={styles.row}>
        <button type="button" className={styles.step} aria-label="Decrease by one" onClick={() => step(-1)}>
          <span aria-hidden="true">−</span>
        </button>
        <input
          id={id}
          className={styles.input}
          type="text"
          inputMode="numeric"
          autoComplete="off"
          value={value === null ? '' : String(value)}
          placeholder={placeholder}
          aria-describedby={hint ? hintId : undefined}
          onChange={(e) => onType(e.target.value)}
        />
        <button type="button" className={styles.step} aria-label="Increase by one" onClick={() => step(1)}>
          <span aria-hidden="true">+</span>
        </button>
      </div>
      {hint ? (
        <p id={hintId} className={styles.hint}>
          {hint}
        </p>
      ) : null}
    </div>
  );
}
