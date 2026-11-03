import styles from './LiveCount.module.css';

// The side card of the Needs step (boards/advisor/Call.dc.html, side layer 1; P1 "Matching so far"): how many
// services meet the criteria so far. The figure is replaced, never animated. A count needs the options read, which
// needs a saved case, so while the form is filled in the card says there is no count yet (brief section 8, gap 1:
// nothing is written as a draft to get one). A polite status, so a changed figure is spoken once.

export function LiveCount({ count }: { count: number | null }) {
  return (
    <section className={styles.card} data-el="ADV-LIVE-COUNT">
      <h2 className={styles.kicker}>As you fill this in</h2>
      <div className={styles.figure} role="status" aria-live="polite">
        {count === null ? (
          <span className={styles.none}>No count yet</span>
        ) : (
          <>
            <span className={styles.number}>{count}</span>{' '}
            <span className={styles.words}>
              {count === 0
                ? 'No service meets the criteria so far'
                : `${count === 1 ? 'service meets' : 'services meet'} the criteria so far`}
            </span>
          </>
        )}
      </div>
      <p className={styles.note}>
        {count === null
          ? 'Nothing is offered until you press See options.'
          : 'The count follows every choice. Nothing is offered until you press the button.'}
      </p>
    </section>
  );
}
