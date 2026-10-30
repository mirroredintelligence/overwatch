import { useId, type ChangeEvent } from 'react';
import styles from './forms.module.css';

// A labelled text input. "Required" and "Optional" are written as words beside the label, outside
// its text, so the accessible name is the label alone. The error and the hint are linked by
// aria-describedby; an invalid field says so with aria-invalid.

export type TextFieldProps = {
  id: string;
  label: string;
  value: string;
  onChange: (next: string) => void;
  requirement?: 'required' | 'optional' | 'none';
  hint?: string;
  error?: string | null;
  type?: 'text' | 'email' | 'tel' | 'date' | 'number' | 'url';
  inputMode?: 'text' | 'numeric' | 'tel' | 'email' | 'decimal' | 'url';
  autoComplete?: string;
  maxLength?: number;
  readOnly?: boolean;
  dataEl?: string;
};

const WORD = { required: 'Required', optional: 'Optional', none: null } as const;

export function TextField({
  id,
  label,
  value,
  onChange,
  requirement = 'required',
  hint,
  error,
  type = 'text',
  inputMode,
  autoComplete,
  maxLength,
  readOnly = false,
  dataEl,
}: TextFieldProps) {
  const hintId = useId();
  const errorId = useId();
  const describedBy = [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(' ') || undefined;
  const word = WORD[requirement];
  return (
    <div className={styles.field} data-el={dataEl}>
      <div className={styles.labelRow}>
        <label className={styles.label} htmlFor={id}>
          {label}
        </label>
        {word !== null ? <span className={styles.word}>{word}</span> : null}
      </div>
      {hint ? (
        <p id={hintId} className={styles.hint}>
          {hint}
        </p>
      ) : null}
      <input
        id={id}
        name={id}
        className={`${styles.input} ${error ? styles.invalid : ''}`}
        type={type}
        inputMode={inputMode}
        autoComplete={autoComplete}
        maxLength={maxLength}
        readOnly={readOnly}
        value={value}
        aria-invalid={error ? 'true' : undefined}
        aria-describedby={describedBy}
        onChange={(event: ChangeEvent<HTMLInputElement>) => onChange(event.target.value)}
      />
      {error ? (
        <p id={errorId} className={styles.error}>
          {error}
        </p>
      ) : null}
    </div>
  );
}
