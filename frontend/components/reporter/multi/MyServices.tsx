'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { bffRequest } from '@/lib/reporter/browser';
import styles from '@/components/reporter/Reporter.module.css';
import { type ServiceRow, stateText } from './serviceState';

// My services (W38): each service on the phone with its state, and how a new one is added.

export function MyServices() {
  const router = useRouter();
  const [rows, setRows] = useState<ServiceRow[] | null>(null);

  useEffect(() => {
    let live = true;
    void bffRequest('/api/bff/reporter/services').then((reply) => {
      if (!live) return;
      if (reply.status === 401) return router.replace('/app/pin');
      const list = (reply.body as { services?: ServiceRow[] } | undefined)?.services;
      setRows(reply.status === 200 && Array.isArray(list) ? list : []);
    });
    return () => {
      live = false;
    };
  }, [router]);

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
      <p>To add a service, ask the SPOA shift lead. New services are added by invitation and checked.</p>
    </main>
  );
}
