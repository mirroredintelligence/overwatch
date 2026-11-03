'use client';

import { useRef, type KeyboardEvent } from 'react';
import styles from './ReasonChips.module.css';

// One reason from a short list (artboard B4, board 2: decline, withdraw, not reached). A radio group with the
// roving focus of the standard pattern: one chip is in the tab order (the chosen one, else the first), the
// arrow keys move the choice and the focus, wrapping at the ends, Home and End go to the first and last. The
// chosen chip also shows a tick, so the choice is not colour alone. The page owns the value.

export type ReasonOption = { readonly value: string; readonly label: string };

export type ReasonChipsProps = {
  /** The group's accessible name (the page shows the question itself). */
  label: string;
  options: readonly ReasonOption[];
  value: string | null;
  onChange: (value: string) => void;
  disabled?: boolean;
  dataEl?: string;
};

export function ReasonChips({ label, options, value, onChange, disabled = false, dataEl }: ReasonChipsProps) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const chosen = options.findIndex((o) => o.value === value);
  const tabbable = chosen === -1 ? 0 : chosen;

  const move = (to: number) => {
    const index = (to + options.length) % options.length;
    onChange(options[index].value);
    refs.current[index]?.focus();
  };

  const onKeyDown = (event: KeyboardEvent, index: number) => {
    if (disabled) return;
    switch (event.key) {
      case 'ArrowRight':
      case 'ArrowDown':
        event.preventDefault();
        move(index + 1);
        break;
      case 'ArrowLeft':
      case 'ArrowUp':
        event.preventDefault();
        move(index - 1);
        break;
      case 'Home':
        event.preventDefault();
        move(0);
        break;
      case 'End':
        event.preventDefault();
        move(options.length - 1);
        break;
    }
  };

  return (
    <div className={styles.group} role="radiogroup" aria-label={label} data-el={dataEl}>
      {options.map((option, index) => {
        const on = index === chosen;
        return (
          <button
            key={option.value}
            ref={(el) => {
              refs.current[index] = el;
            }}
            type="button"
            role="radio"
            aria-checked={on}
            tabIndex={index === tabbable ? 0 : -1}
            disabled={disabled}
            className={`${styles.chip} ${on ? styles.on : ''}`}
            onClick={() => onChange(option.value)}
            onKeyDown={(event) => onKeyDown(event, index)}
          >
            {on ? (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
                <path d="M5 12.5l4.5 4.5L19 7.5" />
              </svg>
            ) : null}
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
