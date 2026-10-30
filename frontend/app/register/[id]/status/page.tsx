import type { Metadata } from 'next';
import { StatusPage } from '@/components/register/StatusPage';
import styles from '@/components/register/register.module.css';

// The applicant's status after submitting (W27).

export const metadata: Metadata = {
  title: 'Your registration - DIUCS capacity',
  robots: { index: false },
};

export default async function StatusRoute({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <main className={styles.main}>
      <div className={styles.panel}>
        <p className={styles.product}>DIUCS capacity</p>
        <div className={styles.card}>
          <StatusPage registrationId={id} />
        </div>
      </div>
    </main>
  );
}
