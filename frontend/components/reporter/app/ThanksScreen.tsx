'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { bffRequest } from '@/lib/reporter/browser';
import { clock } from '@/lib/reporter/times';
import styles from '@/components/reporter/Reporter.module.css';

// After a capacity update (W35): the figure recorded, the next update, and today's reports for this
// service, newest first. The list is read from the BFF; nothing is kept in the browser.

type Item = { at: string; value: number; kind?: string };

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
        // Newest first, by the instant (not by the clock text, which would not sort across midnight).
        setItems([...list].sort((a, b) => Date.parse(b.at) - Date.parse(a.at)));
      }
    });
    return () => {
      live = false;
    };
  }, [serviceId, router]);

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Thank you</h1>
      <p>{`${service}: ${value} ${unit} recorded at ${clock(at)}.`}</p>
      {clock(nextDue) !== '' ? <p>{`Next update due ${clock(nextDue)}`}</p> : null}
      <h2>Today</h2>
      <ul>
        {items.map((item) => (
          <li key={`${item.at}-${item.value}`}>
            <span>{clock(item.at)}</span> <span>{item.value}</span>
          </li>
        ))}
      </ul>
      <p>
        <a href={`/app/respond/${encodeURIComponent(serviceId)}`}>Change it</a>
      </p>
    </main>
  );
}
