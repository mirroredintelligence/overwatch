import type { Metadata } from 'next';
import { Button } from '@/components/ui/Button';
import { RegisterStage } from '@/components/register/RegisterStage';
import styles from '@/components/register/RegisterStage.module.css';

// Submitted for approval: stage 6 of the register frame (Reg board). The applicant is not on the board until
// the test is answered and the shift lead approves. The expected review time and the time of submission are
// not in the back end (the board's "within a working day" is to come from configuration), so neither is shown.

export const metadata: Metadata = {
  title: 'Submitted for approval - Overwatch',
  robots: { index: false },
};

const BACK = '/register/services';

export default async function SubmittedPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <RegisterStage registrationId={id} stage={6} phoneAction={{ primary: { label: 'Back to my services', href: BACK } }}>
      <div className={`${styles.card} ${styles.centred}`}>
        <div className={styles.tick} aria-hidden="true">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
            <path d="M5 12.5l4.5 4.5L19 7.5" />
          </svg>
        </div>
        <h1 className={styles.done}>Submitted. We are checking.</h1>
        <ol className={styles.next}>
          <li>
            <span className={styles.mark} data-done="true" aria-hidden="true">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                <path d="M5 12.5l4.5 4.5L19 7.5" />
              </svg>
            </span>
            <span>
              <strong>Submitted</strong>
            </span>
          </li>
          <li>
            <span className={styles.mark} data-done="false" aria-hidden="true" />
            <span>
              <strong>Checks.</strong> Your shift lead may phone your service.
            </span>
          </li>
          <li>
            <span className={styles.mark} data-done="false" aria-hidden="true" />
            <span>
              <strong>A test text</strong> to the number you gave
            </span>
          </li>
          <li>
            <span className={styles.mark} data-done="false" aria-hidden="true" />
            <span>
              <strong>You are live</strong> on the board
            </span>
          </li>
        </ol>
        <p className={styles.text}>The shift lead will check your details and send a test text to the number you gave.</p>
        <p className={styles.text}>You will get an email when it is approved, or if something needs changing.</p>
        <div className={styles.cardActions}>
          <Button variant="primary" href={BACK} dataEl="REG-SUBMITTED-BACK-BTN">
            Back to my services
          </Button>
        </div>
      </div>
    </RegisterStage>
  );
}
