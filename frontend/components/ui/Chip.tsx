import type { ReactNode } from 'react';
import styles from './Chip.module.css';

export type ChipProps = {
  pressed: boolean;
  onPressedChange: (next: boolean) => void;
  children: ReactNode;
  dataEl?: string;
  /** A chip that is shown but cannot be changed (a recorded score's method is not removed). */
  disabled?: boolean;
  /** Further `data-*` attributes (an opaque reference to tell repeated chips apart). */
  data?: Record<`data-${string}`, string>;
};

export function Chip({ pressed, onPressedChange, children, dataEl, disabled, data }: ChipProps) {
  return (
    <button
      type="button"
      className={styles.chip}
      aria-pressed={pressed}
      onClick={() => onPressedChange(!pressed)}
      data-el={dataEl}
      disabled={disabled}
      {...data}
    >
      {children}
    </button>
  );
}
