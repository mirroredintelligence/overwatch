'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { bffRequest } from '@/lib/reporter/browser';
import styles from '@/components/reporter/Reporter.module.css';

// After a capacity update (W35): the figure recorded, the next update, and today's reports for this
// service, newest first. The list is read from the BFF; nothing is kept in the browser.

type Item = { at: string; value: number };

export function ThanksScreen({
  serviceId,
  service,
  value,
  at,
  nextDue,
  unit = 'referrals',
}: {
  serviceId: string;
  service: string;
  value: number;
  at: string;
  nextDue: string;
  unit?: string;
}) {
  const router = useRouter();
  const [items, setItems] = useState<Item[]>([]);

  useEffect(() => {
    let live = true;
    void bffRequest(`/api/bff/reporter/services/${encodeURIComponent(serviceId)}/history?day=today`).then((reply) => {
      if (!live) return;
      if (reply.status === 401) return router.replace('/app/pin');
      const list = (reply.body as { items?: Item[] } | undefined)?.items;
      if (reply.status === 200 && Array.isArray(list)) {
        setItems([...list].sort((a, b) => (a.at < b.at ? 1 : a.at > b.at ? -1 : 0)));
      }
    });
    return () => {
      live = false;
    };
  }, [serviceId, router]);

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Thank you</h1>
      <p>{`${service}: ${value} ${unit} recorded at ${at}.`}</p>
      <p>{`Next update due ${nextDue}`}</p>
      <h2>Today</h2>
      <ul>
        {items.map((item) => (
          <li key={`${item.at}-${item.value}`}>
            <span>{item.at}</span> <span>{item.value}</span>
          </li>
        ))}
      </ul>
      <p>
        <a href={`/app/respond/${encodeURIComponent(serviceId)}`}>Change it</a>
      </p>
    </main>
  );
}
