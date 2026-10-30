import type { Metadata } from 'next';
import { Button } from '@/components/ui/Button';
import styles from '@/components/register/register.module.css';

// Submitted for approval (W26). The applicant is not on the board until the test is answered and
// the shift lead approves. The expected time is not in the back end yet (see the W26 fragment).

export const metadata: Metadata = {
  title: 'Submitted for approval - DIUCS capacity',
  robots: { index: false },
};

export default async function SubmittedPage({ params }: { params: Promise<{ id: string }> }) {
  await params;
  return (
    <main className={styles.main}>
      <div className={styles.panel}>
        <p className={styles.product}>DIUCS capacity</p>
        <div className={styles.card}>
          <h1 className={styles.heading}>Submitted for approval</h1>
          <p className={styles.text}>
            The shift lead will check your details and send a test text to the number you gave.
          </p>
          <p className={styles.text}>You will get an email when it is approved, or if something needs changing.</p>
          <div className={styles.actions}>
            <Button variant="primary" href="/register/services" dataEl="REG-SUBMITTED-BACK-BTN">
              Back to my services
            </Button>
          </div>
        </div>
      </div>
    </main>
  );
}
