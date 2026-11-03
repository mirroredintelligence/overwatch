'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { bffRequest } from '@/lib/reporter/browser';
import { clock } from '@/lib/reporter/times';
import capacity from '@/components/reporter/CapacityLink.module.css';
import styles from './ThanksScreen.module.css';

// After a capacity update (artboard B6, board 4): the figure recorded, the next update, and today's reports for
// this service, newest first. The figure is the one just recorded and, like the figure card's, never animates.
// The list is read from the BFF; nothing is kept in the browser.

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

  const next = clock(nextDue);

  return (
    <main className={capacity.stack}>
      <section className={`${capacity.card} ${capacity.cardStart} ${styles.thanks}`}>
        <h1 className={`${capacity.heading} ${styles.title}`}>Thank you</h1>
        <p className={`${capacity.body} ${styles.service}`}>{service}</p>
        <p className={capacity.figureRow}>
          <span className={capacity.figure} data-figure={String(value)}>
            {value}
          </span>
          <span className={capacity.unit}>{unit}</span>
        </p>
        <p className={`${capacity.body} ${styles.recorded}`}>{`Recorded at ${clock(at)}.`}</p>
        {next !== '' ? <span className={`${capacity.tag} ${capacity.tagTint}`} data-el="REP-APP-NEXT-DUE">{`Next update due ${next}`}</span> : null}
      </section>
      <section className={styles.today} aria-labelledby="rep-app-today">
        <h2 id="rep-app-today" className={styles.todayTitle}>
          Today
        </h2>
        <ul className={styles.list}>
          {items.map((item) => (
            <li key={`${item.at}-${item.value}`} className={styles.row}>
              <span className={styles.time}>{clock(item.at)}</span>
              <span className={styles.what}>{`${item.value} ${unit}`}</span>
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
