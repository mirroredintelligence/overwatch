import styles from './Reporter.module.css';

// The link could not be read. That is not the same as expired, so the page does not say it was.
export function LinkUnavailable() {
  return (
    <main className={styles.page}>
      <p className={styles.eyebrow}>DIUCS capacity update</p>
      <p className={styles.question}>We could not load this link. Try again in a few minutes.</p>
    </main>
  );
}
