'use client';

import { Chip } from '@/components/ui/Chip';
import type { Option } from '@/lib/register/options';
import styles from './forms.module.css';

// A group of toggle chips with a legend (W54 onwards). The group is a fieldset with a legend, so its
// name is read with it; each chip is a button with aria-pressed. The fieldset takes focus from an
// error summary link, so it has an id and tabIndex -1.

export type ChipGroupProps = {
  id: string;
  legend: string;
  options: readonly Option[];
  selected: readonly string[];
  /** One choice (the chip pressed last) or several. */
  multiple?: boolean;
  requirement?: 'required' | 'optional';
  onChange: (next: string[]) => void;
  error?: string | null;
  dataEl?: string;
};

export function ChipGroup({ id, legend, options, selected, multiple = false, requirement, onChange, error = null, dataEl }: ChipGroupProps) {
  const errorId = `${id}-error`;
  const toggle = (value: string, pressed: boolean) => {
    if (multiple) {
      onChange(pressed ? [...selected, value] : selected.filter((item) => item !== value));
      return;
    }
    onChange(pressed ? [value] : []);
  };
  return (
    <fieldset
      id={id}
      tabIndex={-1}
      className={styles.group}
      aria-describedby={error ? errorId : undefined}
      data-el={dataEl}
    >
      <legend className={styles.legend}>{legend}</legend>
      {requirement !== undefined ? (
        <span className={styles.word}>{requirement === 'required' ? 'Required' : 'Optional'}</span>
      ) : null}
      <div className={styles.chips}>
        {options.map((option) => (
          <Chip
            key={option.value}
            pressed={selected.includes(option.value)}
            onPressedChange={(pressed) => toggle(option.value, pressed)}
            dataEl={dataEl === undefined ? undefined : `${dataEl}-${option.value}`}
          >
            {option.label}
          </Chip>
        ))}
      </div>
      {error ? (
        <p id={errorId} className={styles.error}>
          {error}
        </p>
      ) : null}
    </fieldset>
  );
}
