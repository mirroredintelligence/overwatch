import { Button } from '@/components/ui/Button';
import styles from './finish.module.css';

// The state after "Save outcome" (W15). It names what was kept and what was cleared, and it holds no
// postcode or needs: the screen that showed them has been taken down. It is the address ?closed=1.

export function CallClosed({ reference }: { reference: string | null }) {
  return (
    <section className={styles.closed} aria-labelledby="call-closed-heading">
      <div className={styles.closedHead}>
        <span className={styles.tick} aria-hidden="true">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round" focusable="false">
            <path d="M5 12.5l4.5 4.5L19 7.5" />
          </svg>
        </span>
        <div>
          <h1 id="call-closed-heading" className={styles.closedTitle}>
            Call closed
          </h1>
          <p className={styles.text}>
            {reference === null
              ? 'The case is saved. The postcode has been cleared from this screen.'
              : `Reference ${reference} is saved. The postcode has been cleared from this screen.`}
          </p>
        </div>
      </div>
      <div className={styles.kept}>
        <div className={styles.keptBox}>
          <h2 className={styles.boxLabel}>Kept for audit</h2>
          <ul className={styles.list}>
            <li>Need category, age band, urgency and scores</li>
            <li>Destination, outcome and times</li>
            <li>What the board showed</li>
          </ul>
        </div>
        <div className={styles.keptBox}>
          <h2 className={styles.boxLabel}>Cleared</h2>
          <ul className={styles.list}>
            <li>Postcode</li>
            <li>Anything free-typed on the call</li>
          </ul>
        </div>
      </div>
      <div className={styles.actions}>
        <Button variant="primary" href="/advisor" dataEl="ADV-FIN-NEXT-BTN">
          Start next call
        </Button>
        <a className={styles.link} href="/advisor/board">
          Back to the board
        </a>
        <p className={styles.note}>Retention periods are set by information governance.</p>
      </div>
    </section>
  );
}
