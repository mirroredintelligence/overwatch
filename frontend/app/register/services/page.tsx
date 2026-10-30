import type { Metadata } from 'next';
import { MyServices } from '@/components/register/MyServices';
import styles from '@/components/register/register.module.css';

// My services (W26): the reporter's services and where each one stands.

export const metadata: Metadata = {
  title: 'My services - DIUCS capacity',
  robots: { index: false },
};

export default async function MyServicesPage() {
  return (
    <main className={styles.main}>
      <div className={styles.panel}>
        <div className={styles.card}>
          <MyServices />
        </div>
      </div>
    </main>
  );
}
