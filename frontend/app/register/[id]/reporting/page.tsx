import type { Metadata } from 'next';
import { ReportingForm } from '@/components/register/ReportingForm';
import styles from '@/components/register/register.module.css';

// Registration step 4, how the service reports capacity (W26).

export const metadata: Metadata = {
  title: 'How will you report capacity? - DIUCS capacity',
  robots: { index: false },
};

export default async function ReportingPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <main className={styles.main}>
      <div className={styles.panel}>
        <div className={styles.card}>
          <ReportingForm registrationId={id} />
        </div>
      </div>
    </main>
  );
}
