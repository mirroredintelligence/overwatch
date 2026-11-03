import { Button } from '@/components/ui/Button';
import { StatusTag } from '@/components/ui/StatusTag';
import { londonDayMonthTime } from '@/lib/register/time';
import { StatusTracker } from '../StatusTracker';
import styles from '../status.module.css';

// Submitted, being checked (W27, ApprovalApplicant panel 2). The tracker shows where it stands.

export function InReview({ submittedAt }: { submittedAt?: string }) {
  return (
    <section className={styles.card} aria-label="In review">
      <div className={styles.tagRow}>
        <StatusTag variant="waiting">In review</StatusTag>
      </div>
      <h1 className={styles.heading}>Submitted. We are checking.</h1>
      <StatusTracker
        current="Checks"
        details={{
          Submitted: submittedAt === undefined ? undefined : londonDayMonthTime(submittedAt),
          Checks: 'In progress. The shift lead may phone your service.',
        }}
      />
      <p className={styles.text}>We will tell you by notification.</p>
      <div className={styles.actions}>
        <Button variant="secondary" href="/register/services">
          Back to my services
        </Button>
      </div>
    </section>
  );
}
