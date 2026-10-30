import type { Metadata } from 'next';
import { LocationForm } from '@/components/register/LocationForm';
import styles from '@/components/register/register.module.css';

// Registration step 2, where the service is (W24). The form does the lookup through the BFF.

export const metadata: Metadata = {
  title: 'Where is the service? - DIUCS capacity',
  robots: { index: false },
};

export default async function LocationPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <main className={styles.main}>
      <div className={styles.panel}>
        <div className={styles.card}>
          <LocationForm registrationId={id} />
        </div>
      </div>
    </main>
  );
}
