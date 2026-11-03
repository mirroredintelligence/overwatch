import styles from './AttentionStat.module.css';

// One of the counters at the top of the shift (the board's "Needs you first"): the figure, what it counts, and
// a few words on why. The figure is plain text and never animates. An urgent counter has an amber border and a
// warning icon as well as its words, so colour is never the only sign. A zero is not urgent.

export type AttentionStatProps = {
  count: number;
  /** What is counted, in words that follow the figure: "services to chase". */
  label: string;
  /** Why it is counted: "overdue now". */
  hint: string;
  urgent?: boolean;
};

export function AttentionStat({ count, label, hint, urgent = false }: AttentionStatProps) {
  const raised = urgent && count > 0;
  return (
    <div
      role="group"
      aria-label={`${count} ${label}, ${hint}`}
      className={styles.stat}
      data-urgent={raised ? 'true' : undefined}
    >
      <span className={styles.count} aria-hidden="true">
        {count}
      </span>
      <span className={styles.words} aria-hidden="true">
        <span>{label}</span>
        <span className={styles.hint}>{hint}</span>
      </span>
      {raised ? (
        <svg
          className={styles.icon}
          width="22"
          height="22"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
          focusable="false"
        >
          <path d="M12 3l10 18H2z" />
          <path d="M12 10v5M12 18h.01" />
        </svg>
      ) : null}
    </div>
  );
}
