import Link from 'next/link';
import { londonDayMonthTime } from '@/lib/register/time';
import { StatusTracker } from '../StatusTracker';
import styles from '../register.module.css';

// Submitted, being checked (W27, ApprovalApplicant panel 2). The tracker shows where it stands.

export function InReview({ submittedAt }: { submittedAt?: string }) {
  return (
    <div className={styles.stack}>
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
        <Link className={styles.backLink} href="/register/services">
          Back to my services
        </Link>
      </div>
    </div>
  );
}
