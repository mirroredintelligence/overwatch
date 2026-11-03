import styles from './SetupProgress.module.css';

const TOTAL = 5;

// Five segments, filled up to the current step. The bar is named by the step it is on; the segments are decoration.
export function SetupProgress({ step }: { step: number }) {
  const current = Math.min(TOTAL, Math.max(1, Math.round(step)));
  const label = `Step ${current} of ${TOTAL}`;
  return (
    <div className={styles.bar} role="progressbar" aria-label={label} aria-valuemin={1} aria-valuemax={TOTAL} aria-valuenow={current} aria-valuetext={label}>
      {Array.from({ length: TOTAL }, (_, i) => (
        <span key={i} className={styles.segment} data-segment data-filled={i < current ? 'true' : 'false'} />
      ))}
    </div>
  );
}
