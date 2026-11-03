'use client';

import { useId } from 'react';
import styles from './SettingRow.module.css';

// One setting: its label, "Now X · Default Y", the control that fits it (chips, a number or text) and, when it
// differs from the default, "Use the default". With no control the value is shown as a badge (read only).

export type SettingControl =
  | { kind: 'chips'; options: readonly string[]; value: readonly string[]; onChange: (next: string[]) => void }
  | { kind: 'number'; value: number | null; min?: number; max?: number; step?: number; unit?: string; onChange: (next: number) => void }
  | { kind: 'text'; value: string; onChange: (next: string) => void };

export function SettingRow({
  label,
  now,
  defaultValue,
  changed = false,
  onUseDefault,
  control,
}: {
  label: string;
  /** The value in words, as it stands now. */
  now: string;
  /** The default in words. */
  defaultValue: string;
  /** Differs from what is in force: the row's edge says so. */
  changed?: boolean;
  onUseDefault?: () => void;
  control?: SettingControl;
}) {
  const id = useId();
  const labelId = `${id}-label`;
  return (
    <div className={styles.row} data-changed={changed}>
      <div className={styles.text}>
        <div className={styles.label} id={labelId}>
          {label}
        </div>
        <div className={styles.meta}>
          Now {now} · Default {defaultValue}
        </div>
        {control?.kind === 'chips' ? (
          <div className={styles.chips} role="group" aria-labelledby={labelId}>
            {control.options.map((option) => {
              const on = control.value.includes(option);
              return (
                <button
                  key={option}
                  type="button"
                  className={styles.chip}
                  aria-pressed={on}
                  onClick={() => control.onChange(on ? control.value.filter((v) => v !== option) : [...control.value, option])}
                >
                  <span aria-hidden="true">{on ? '✓' : '+'} </span>
                  {option}
                </button>
              );
            })}
          </div>
        ) : null}
        {control?.kind === 'number' || control?.kind === 'text' ? (
          <div className={styles.field}>
            <input
              className={styles.input}
              aria-labelledby={labelId}
              {...(control.kind === 'number'
                ? {
                    type: 'number',
                    inputMode: 'numeric' as const,
                    min: control.min,
                    max: control.max,
                    step: control.step,
                    value: control.value ?? '',
                    onChange: (e) => {
                      if (e.target.value !== '') control.onChange(Number(e.target.value));
                    },
                  }
                : { type: 'text', autoComplete: 'off', value: control.value, onChange: (e) => control.onChange(e.target.value) })}
            />
            {control.kind === 'number' && control.unit ? <span className={styles.unit}>{control.unit}</span> : null}
          </div>
        ) : null}
        {changed && onUseDefault ? (
          <button type="button" className={styles.reset} aria-label={`Use the default for ${label}`} onClick={onUseDefault}>
            Use the default
          </button>
        ) : null}
      </div>
      {control === undefined ? <span className={styles.value}>{now}</span> : null}
    </div>
  );
}
