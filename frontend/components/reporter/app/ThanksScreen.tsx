'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { bffRequest } from '@/lib/reporter/browser';
import { Button } from '@/components/ui/Button';
import { clock } from '@/lib/reporter/times';
import { Panel } from '../parts/Panel';
import partStyles from '../parts/Parts.module.css';
import { StatusMark } from '../parts/StatusMark';
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
      <StatusMark tone="done" dataEl="REP-APP-THANKS-MARK" />
      <h1 className={styles.title}>Thank you</h1>
      <p className={styles.question}>{`${service}: ${value} ${unit} recorded at ${clock(at)}.`}</p>
      {clock(nextDue) !== '' ? <Panel dataEl="REP-APP-NEXT-DUE">{`Next update due ${clock(nextDue)}`}</Panel> : null}
      <section className={partStyles.card} aria-labelledby="rep-app-today">
        <h2 id="rep-app-today" className={partStyles.cardTitle}>
          Today
        </h2>
        <ul className={partStyles.today}>
          {items.map((item) => (
            <li key={`${item.at}-${item.value}`} className={partStyles.todayItem}>
              <span>{clock(item.at)}</span> <span>{item.value}</span>
            </li>
          ))}
        </ul>
      </section>
      <Button variant="secondary" href={`/app/respond/${encodeURIComponent(serviceId)}`} dataEl="REP-APP-CHANGE-IT">
        Change it
      </Button>
    </main>
  );
}
