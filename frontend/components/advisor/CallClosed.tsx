import { Button } from '@/components/ui/Button';
import styles from './finish.module.css';

// The state after "Save outcome" (W15). It names what was kept and what was cleared, and it holds no
// postcode or needs: the screen that showed them has been taken down.

export function CallClosed({ reference }: { reference: string | null }) {
  return (
    <section className={styles.screen} aria-labelledby="call-closed-heading">
      <h2 id="call-closed-heading" className={styles.heading}>
        Call closed
      </h2>
      <p className={styles.status}>Case closed</p>
      <p className={styles.text}>{`${reference === null ? 'The case' : `Case ${reference}`} is saved. The postcode has been cleared from this screen.`}</p>
      <h3 className={styles.legend}>Kept for audit</h3>
      <p className={styles.text}>
        Need category, age band, urgency, scores, destination, outcome, times, and what the board showed.
      </p>
      <h3 className={styles.legend}>Cleared</h3>
      <p className={styles.text}>Postcode.</p>
      <p className={styles.note}>Retention periods are for IG to set.</p>
      <div className={styles.actions}>
        <Button variant="primary" href="/advisor" dataEl="ADV-FIN-NEXT-BTN">
          Start next call
        </Button>
      </div>
    </section>
  );
}
