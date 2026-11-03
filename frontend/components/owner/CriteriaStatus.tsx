import { londonTime } from '@/lib/board/format';
import styles from './CriteriaStatus.module.css';

// The tracker after a send (W30, ui-screens CriteriaOwner screen 7, boards/lead/OwnerReview.dc.html step 6). The live
// version stays live until a second person approves the sent one; a send back comes with its note.

// The step's shape: a filled circle with a tick when done, a dashed ring when it is waiting, a faint ring when it is
// still to come. The word beside it carries the meaning; the shape is decoration.
function Shape({ state }: { state: 'done' | 'waiting' | 'later' }) {
  if (state === 'done') {
    return (
      <span className={`${styles.shape} ${styles.done}`} aria-hidden="true">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={3} strokeLinecap="round" strokeLinejoin="round" focusable="false">
          <path d="M5 12.5l4.5 4.5L19 7.5" />
        </svg>
      </span>
    );
  }
  return <span className={`${styles.shape} ${state === 'waiting' ? styles.waiting : styles.later}`} aria-hidden="true" />;
}

export function CriteriaStatus({
  version,
  liveVersion,
  sentAt,
  waiting,
}: {
  /** The version that was sent. */
  version: number;
  /** The version advisors see now. */
  liveVersion: number;
  sentAt?: string;
  waiting: boolean;
}) {
  return (
    <div role="status" className={styles.card}>
      <span className={styles.badge} aria-hidden="true">
        <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" focusable="false">
          {waiting ? <path d="M12 7v5l3 2" /> : <path d="M5 12.5l4.5 4.5L19 7.5" />}
          {waiting ? <circle cx="12" cy="12" r="9" /> : null}
        </svg>
      </span>
      <h2 className={styles.heading}>{waiting ? 'Waiting for approval' : 'Live'}</h2>
      {waiting ? (
        <>
          <p className={styles.lede}>{`Version ${liveVersion} stays live until someone else approves version ${version}.`}</p>
          <p className={styles.lede}>You will be told when they have, or if they send it back with a note.</p>
        </>
      ) : (
        <p className={styles.lede}>{`Advisors see version ${version}.`}</p>
      )}
      <ol className={styles.steps}>
        <li className={styles.step}>
          <Shape state="done" />
          <span>{sentAt !== undefined ? `Sent by you at ${londonTime(sentAt)}` : 'Sent by you'}</span>
        </li>
        <li className={styles.step}>
          <Shape state={waiting ? 'waiting' : 'done'} />
          <span>{waiting ? 'Waiting for a second approver' : 'Approved by a second person'}</span>
        </li>
        <li className={styles.step}>
          <Shape state={waiting ? 'later' : 'done'} />
          <span className={waiting ? styles.muted : undefined}>Live for advisors</span>
        </li>
      </ol>
    </div>
  );
}
