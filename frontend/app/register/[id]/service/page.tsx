import type { Metadata } from 'next';
import { ServiceForm } from '@/components/register/ServiceForm';
import styles from '@/components/register/register.module.css';

// Registration step 3, describing the service (W25). The form loads the invitation and the fixed-site
// answer through the BFF.

export const metadata: Metadata = {
  title: 'Describe the service - DIUCS capacity',
  robots: { index: false },
};

export default async function ServicePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <main className={styles.main}>
      <div className={styles.panel}>
        <div className={styles.card}>
          <ServiceForm registrationId={id} />
        </div>
      </div>
    </main>
  );
}
