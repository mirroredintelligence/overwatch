import styles from './ProgressBar5.module.css';

// Five segments, `done` of them filled (operator organisations list and funnel, O2). The whole bar is one
// image with the name "n of 5 parts done"; the words next to it (which part is next) belong to the page.

const PARTS = 5;

export function ProgressBar5({ done }: { done: number }) {
  const filled = Math.min(PARTS, Math.max(0, Math.floor(Number.isFinite(done) ? done : 0)));
  return (
    <div className={styles.bar} role="img" aria-label={`${filled} of ${PARTS} parts done`}>
      {Array.from({ length: PARTS }, (_, i) => (
        <span key={i} className={styles.seg} data-seg={i < filled ? 'filled' : 'empty'} />
      ))}
    </div>
  );
}
