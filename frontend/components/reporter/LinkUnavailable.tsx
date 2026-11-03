import styles from './CapacityLink.module.css';
import { LinkFrame } from './parts/LinkFrame';

// The link could not be read. That is not the same as expired, so the page does not say it was.
export function LinkUnavailable() {
  return (
    <LinkFrame noLoginTag={false}>
      <main className={styles.stack}>
        <section className={`${styles.card} ${styles.cardStart}`}>
          <h1 className={styles.heading}>This link did not open</h1>
          <p className={styles.body}>We could not load this link. Try again in a few minutes.</p>
        </section>
      </main>
    </LinkFrame>
  );
}
