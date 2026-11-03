import type { Metadata } from 'next';
import { StatusPage } from '@/components/register/StatusPage';
import styles from '@/components/register/status.module.css';

// The applicant's status after submitting (W27).

export const metadata: Metadata = {
  title: 'Your registration - Overwatch',
  robots: { index: false },
};

export default async function StatusRoute({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <main className={styles.page}>
      <div className={styles.column}>
        <StatusPage registrationId={id} />
      </div>
    </main>
  );
}
