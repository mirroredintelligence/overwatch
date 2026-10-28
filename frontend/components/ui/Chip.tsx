import type { ReactNode } from 'react';
import styles from './Chip.module.css';

export type ChipProps = {
  pressed: boolean;
  onPressedChange: (next: boolean) => void;
  children: ReactNode;
  dataEl?: string;
};

export function Chip({ pressed, onPressedChange, children, dataEl }: ChipProps) {
  return (
    <button
      type="button"
      className={styles.chip}
      aria-pressed={pressed}
      onClick={() => onPressedChange(!pressed)}
      data-el={dataEl}
    >
      {children}
    </button>
  );
}
