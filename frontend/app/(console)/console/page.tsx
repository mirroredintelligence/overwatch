import type { Metadata } from 'next';
import { FindSession } from '@/components/console/FindSession';
import styles from '@/components/console/Console.module.css';
import { getSession } from '@/lib/auth/session';

export const metadata: Metadata = {
  title: 'DIUCS console: find a session',
};

// Read at every request: the console never shows a cached session list or timeline.
export const dynamic = 'force-dynamic';

// The proxy sends only a support session here (proxy.ts, W09). This check is the page's own, so a
// page read on its own still answers the right thing.
export default async function ConsolePage() {
  const session = await getSession();
  if (!session || session.role !== 'support') {
    return (
      <main className={styles.page}>
        <p role="alert" className={styles.alert}>You do not have access to the console.</p>
      </main>
    );
  }
  return <FindSession />;
}
