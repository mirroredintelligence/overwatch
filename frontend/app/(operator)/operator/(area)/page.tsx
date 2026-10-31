import type { Metadata } from 'next';
import { TenantList } from '@/components/operator/TenantList';
import styles from '@/components/admin/admin.module.css';
import { getOperatorSession } from '@/lib/operator/session';

export const metadata: Metadata = { title: 'Tenants - platform console', robots: { index: false } };
export const dynamic = 'force-dynamic';

// The tenants (TEN-083), at /operator. Read at every request: the console never shows a cached list.
export default async function Page() {
  const session = await getOperatorSession();
  if (session === null) {
    return (
      <main className={styles.page}>
        <p role="alert" className={styles.problem}>
          You do not have access to the platform console.
        </p>
      </main>
    );
  }
  return <TenantList role={session.role} />;
}
