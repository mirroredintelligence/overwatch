'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { Loading, SkeletonRows } from '@/components/ui/Skeleton';
import { StatusTag, type StatusTagVariant } from '@/components/ui/StatusTag';
import { bffRequest } from '@/lib/reporter/browser';
import { clock } from '@/lib/reporter/times';
import styles from '@/components/reporter/Reporter.module.css';
import multi from './MyServices.module.css';
import { type ServiceRow, type ServiceState, readRows } from './serviceState';

// My services (W38, B7): each service on the phone with its state, and how a new one is added. A state is a
// shape and a word (StatusTag); only a due service carries an Update button, to that one service.

const VARIANT: Record<ServiceState, StatusTagVariant> = { confirmed: 'confirmed', due: 'due', paused: 'paused' };

/** The word on the state tag: the time a service was last confirmed, or the state itself. */
function tagWord(row: ServiceRow): string {
  if (row.state === 'paused') return 'Paused';
  if (row.state === 'due') return 'Due now';
  const at = clock(row.at);
  return at === '' ? 'Confirmed' : `Confirmed ${at}`;
}

/** The line under the name, only when the back end has the instant; nothing is invented. */
function detailText(row: ServiceRow): string | null {
  if (row.state === 'confirmed') {
    const next = clock(row.nextDue);
    return next === '' ? null : `Next due ${next}`;
  }
  if (row.state === 'due') {
    const by = clock(row.replyBy);
    return by === '' ? null : `Reply by ${by}`;
  }
  return null;
}

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

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>My services</h1>
      {failed ? <Banner tone="warning" title="We could not load your services. Try again shortly." /> : null}
      {!failed && rows === null ? (
        <Loading label="Loading your services.">
          <SkeletonRows count={3} />
        </Loading>
      ) : null}
      {rows !== null && rows.length === 0 ? (
        <section className={multi.empty}>
          <span className={multi.emptyMark} aria-hidden="true">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" focusable="false">
              <rect x="3" y="3" width="7" height="7" rx="1.5" />
              <rect x="14" y="3" width="7" height="7" rx="1.5" />
              <rect x="3" y="14" width="7" height="7" rx="1.5" />
              <rect x="14" y="14" width="7" height="7" rx="1.5" />
            </svg>
          </span>
          <h2 className={multi.emptyTitle}>You have no services yet</h2>
          <p>To add one, ask the shift lead. New services are added by invitation and checked.</p>
        </section>
      ) : null}
      {rows !== null && rows.length > 0 ? (
        <>
          <ul className={multi.list}>
            {rows.map((row) => {
              const detail = detailText(row);
              return (
                <li key={row.id} className={`${multi.card} ${multi[row.state]}`} data-state={row.state}>
                  <div className={multi.head}>
                    <strong className={multi.name}>{row.name}</strong>
                    <StatusTag variant={VARIANT[row.state]}>{tagWord(row)}</StatusTag>
                  </div>
                  {detail !== null ? <p className={multi.detail}>{detail}</p> : null}
                  {row.state === 'due' ? (
                    <div className={multi.action}>
                      <Button variant="primary" href={`/app/respond/${encodeURIComponent(row.id)}`} dataEl="REP-SERVICES-UPDATE">
                        {`Update ${row.name}`}
                      </Button>
                    </div>
                  ) : null}
                  {row.pendingAcceptance ? <Link href={`/app/services/${encodeURIComponent(row.id)}/added`}>Check the new service</Link> : null}
                </li>
              );
            })}
          </ul>
          <p className={multi.note}>To add a service, ask the shift lead. New services are added by invitation and checked.</p>
        </>
      ) : null}
    </main>
  );
}
