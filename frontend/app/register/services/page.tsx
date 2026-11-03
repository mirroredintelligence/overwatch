import type { Metadata } from 'next';
import { MyServices } from '@/components/register/MyServices';
import styles from '@/components/register/entry.module.css';

// My services (W26, artboard RegStatus): the reporter's services and where each one stands.

export const metadata: Metadata = {
  title: 'My services - Overwatch',
  robots: { index: false },
};

export default async function MyServicesPage() {
  return (
    <main className={styles.page}>
      <div className={`${styles.column} ${styles.columnWide}`}>
        <MyServices />
      </div>
    </main>
  );
}
