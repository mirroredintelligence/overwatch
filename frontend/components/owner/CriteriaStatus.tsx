import { londonTime } from '@/lib/board/format';
import styles from '@/components/lead/lead.module.css';

// The tracker after a send (W30, ui-screens CriteriaOwner screen 7). Advisors keep the current version
// until the second approval is given; a send back comes with its note.

export function CriteriaStatus({ version, sentAt, waiting }: { version: number; sentAt?: string; waiting: boolean }) {
  return (
    <div role="status" className={styles.page}>
      <p className={styles.meta}>{`Version ${version}`}</p>
      <h2 className={styles.heading}>{waiting ? 'Waiting for approval' : 'Live'}</h2>
      <ol className={styles.steps}>
        <li>
          <span>Sent</span> <span>{sentAt !== undefined ? `${londonTime(sentAt)}, by you` : 'by you'}</span>
        </li>
        <li>
          <span>Second approval</span> <span>Clinical lead</span>
        </li>
        <li>
          <span>Live</span> <span>{`Advisors see version ${version}`}</span>
        </li>
      </ol>
      <p className={styles.hint}>We will tell you by notification. If it is sent back, you will see the note.</p>
    </div>
  );
}
