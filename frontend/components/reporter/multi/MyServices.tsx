'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { bffRequest } from '@/lib/reporter/browser';
import styles from '@/components/reporter/Reporter.module.css';
import { type ServiceRow, readRows, stateText } from './serviceState';

// My services (W38): each service on the phone with its state, and how a new one is added.

export function MyServices() {
  const router = useRouter();
  const [rows, setRows] = useState<ServiceRow[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    void bffRequest('/api/bff/reporter/services').then((reply) => {
      if (!live) return;
      if (reply.status === 401) return router.replace('/app/pin');
      const list = reply.status === 200 ? readRows(reply.body) : null;
      if (list === null) setFailed(true);
      else setRows(list);
      return undefined;
    });
    return () => {
      live = false;
    };
  }, [router]);

  if (failed) return <main className={styles.page}><p>We could not load your services. Try again shortly.</p></main>;

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>My services</h1>
      <ul>
        {(rows ?? []).map((row) => (
          <li key={row.id}>
            <strong>{row.name}</strong>
            <p>{stateText(row)}</p>
            {row.pendingAcceptance ? (
              <Link href={`/app/services/${encodeURIComponent(row.id)}/added`}>Check the new service</Link>
            ) : null}
          </li>
        ))}
      </ul>
      <p>To add a service, ask the shift lead. New services are added by invitation and checked.</p>
    </main>
  );
}
