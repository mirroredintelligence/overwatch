import type { Metadata } from 'next';
import { Button } from '@/components/ui/Button';
import { RegisterStage } from '@/components/register/RegisterStage';
import styles from '@/components/register/RegisterStage.module.css';

// Register a service: the start page, stage 0 of the register frame (Reg board). It lists what to have ready
// and leads on to step 1 (organisation). "Save and come back later" is in the frame's top bar.

export const metadata: Metadata = {
  title: 'Register a service - Overwatch',
  robots: { index: false },
};

const READY = [
  'Organisation name and ODS code',
  'The address of the site, or the area you cover',
  'A phone number the shift lead can call',
  'Who owns your criteria, and when they are next reviewed',
  'A mobile number or email for capacity updates',
];

export default async function StartPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const base = `/register/${encodeURIComponent(id)}`;

  return (
    <RegisterStage registrationId={id} stage={0} phoneAction={{ primary: { label: 'Start', href: `${base}/organisation` } }}>
      <div className={styles.card}>
        <h1 className={styles.heading}>Register your service</h1>
        <p className={styles.lead}>It takes about 10 minutes. Have these ready:</p>
        <ul className={styles.ready}>
          {READY.map((item, i) => (
            <li key={item}>
              <span className={styles.number} aria-hidden="true">
                {i + 1}
              </span>
              {item}
            </li>
          ))}
        </ul>
        <div className={styles.cardActions}>
          <Button variant="primary" href={`${base}/organisation`} dataEl="REG-START-BTN">
            Start
          </Button>
        </div>
      </div>
    </RegisterStage>
  );
}
