import { Button } from '@/components/ui/Button';
import { StatusTag } from '@/components/ui/StatusTag';
import styles from '../status.module.css';

// Needs changes (W27, ApprovalApplicant panel 3): the notes, who sent them, and the two ways on.

export function NeedsChanges({ notes, noteFrom, registrationId, spoaPhone }: {
  notes: string[];
  noteFrom?: { role: string };
  registrationId: string;
  spoaPhone?: string;
}) {
  const digits = spoaPhone?.replace(/[\s-]/g, '');
  return (
    <section className={`${styles.card} ${styles.cardProblem}`} aria-label="Needs changes">
      <div className={styles.tagRow}>
        <StatusTag variant="problem">Needs changes</StatusTag>
      </div>
      <h1 className={styles.heading}>A few things to fix</h1>
      <ol className={styles.list} aria-label="Notes from the shift lead">
        {notes.map((note, index) => (
          <li key={`${index}-${note}`}>{note}</li>
        ))}
      </ol>
      {noteFrom !== undefined ? <p className={styles.note}>From {noteFrom.role}.</p> : null}
      <div className={styles.actions}>
        <Button variant="primary" href={`/register/${encodeURIComponent(registrationId)}/review`} dataEl="REG-STATUS-FIX-BTN">
          Fix and resubmit
        </Button>
      </div>
      {digits !== undefined && spoaPhone !== undefined ? (
        <div className={styles.stack}>
          <p className={styles.note}>Phone the shift lead on</p>
          <Button variant="secondary" href={`tel:${digits}`} dataEl="REG-STATUS-PHONE-BTN">
            {spoaPhone}
          </Button>
        </div>
      ) : null}
    </section>
  );
}
