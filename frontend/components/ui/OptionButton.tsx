import type { ReactNode } from 'react';
import styles from './OptionButton.module.css';

export type OptionButtonProps = {
  selected: boolean;
  onSelect: () => void;
  children: ReactNode;
  hint?: ReactNode;
  dataEl?: string;
};

function Icon({ selected }: { selected: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className={styles.icon}
    >
      <circle cx="12" cy="12" r="9" />
      {selected ? <path d="M8 12.5l2.5 2.5L16 9.5" /> : null}
    </svg>
  );
}

export function OptionButton({ selected, onSelect, children, hint, dataEl }: OptionButtonProps) {
  return (
    <button
      type="button"
      className={styles.option}
      aria-pressed={selected}
      onClick={onSelect}
      data-el={dataEl}
    >
      <Icon selected={selected} />
      <span className={styles.text}>
        <span className={styles.label}>{children}</span>
        {hint !== undefined ? <span className={styles.hint}>{hint}</span> : null}
      </span>
    </button>
  );
}
