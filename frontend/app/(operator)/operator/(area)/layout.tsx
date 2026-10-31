import type { ReactNode } from 'react';
import { AdminShell } from '@/components/admin/AdminShell';
import styles from '@/components/admin/admin.module.css';
import { getOperatorSession } from '@/lib/operator/session';

// The console's pages (TEN-083): the shared admin frame (logo, the role's navigation, who is signed in and the
// way to sign out) around the page. The proxy keeps these pages to a signed-in operator; this check is the
// layout's own, so a page read on its own still says what it is not for.

export default async function ConsoleLayout({ children }: { children: ReactNode }) {
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
  return (
    <AdminShell portal="operator" role={session.role}>
      {children}
    </AdminShell>
  );
}
