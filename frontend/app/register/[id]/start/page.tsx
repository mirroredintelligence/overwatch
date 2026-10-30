import type { Metadata } from 'next';
import { Button } from '@/components/ui/Button';
import styles from '@/components/register/register.module.css';

// Register a service: the start page (W23, artboard OnboardReporter1). It lists what to have ready
// and leads on to step 1 (organisation, W54) or back to sign-in with the saved-draft note.

export const metadata: Metadata = {
  title: 'Register a service - DIUCS capacity',
  robots: { index: false },
};

const READY = [
  'Organisation name and ODS code',
  'The address of the site, or the area you cover',
  'A phone number the coordination team can call',
  'Who owns your criteria, and when they are next reviewed',
  'A mobile number or email for capacity updates',
];

export default async function StartPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const base = `/register/${encodeURIComponent(id)}`;

  return (
    <main className={styles.main}>
      <div className={styles.panel}>
        <p className={styles.product}>DIUCS capacity</p>
        <h1 className={styles.heading}>Register a service</h1>
        <div className={styles.card}>
          <p className={styles.text}>It takes about 10 minutes. Have these ready:</p>
          <ul className={styles.list}>
            {READY.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          <div className={styles.actions}>
            <Button variant="primary" href={`${base}/organisation`} dataEl="REG-START-BTN">
              Start
            </Button>
            <Button variant="secondary" href="/register?saved=1" dataEl="REG-START-LATER-BTN">
              Save and come back later
            </Button>
          </div>
          <p className={styles.note}>Drafts are saved as you go. Nothing is live until the shift lead approves it.</p>
        </div>
      </div>
    </main>
  );
}
