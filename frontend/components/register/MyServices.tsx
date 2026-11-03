'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { Loading, SkeletonRows } from '@/components/ui/Skeleton';
import { StatusTag, type StatusTagVariant } from '@/components/ui/StatusTag';
import { loadMine, type MyService } from '@/lib/register/browser';
import styles from './entry.module.css';

// My services (W26, artboard RegStatus): one row per service the reporter has, its state as a shape and a
// word, and one action to its status page. A new service comes by invitation from the shift lead, never
// from here: there is no button to register another.

const STATES: Record<MyService['state'], { word: string; variant: StatusTagVariant; action: string }> = {
  active: { word: 'Active', variant: 'live', action: 'Edit' },
  'pending-approval': { word: 'Pending approval', variant: 'waiting', action: 'Open' },
  'review-due': { word: 'Review due', variant: 'due', action: 'Review' },
  'not-approved': { word: 'Not approved', variant: 'closed', action: 'Open' },
};
const LOAD_FAILED = 'We could not load your registration. Try again later.';
const SIGNED_OUT = 'Please sign in again.';

type Load = { kind: 'loading' } | { kind: 'open'; services: MyService[] } | { kind: 'unavailable' } | { kind: 'signed-out' };

export function MyServices() {
  const [load, setLoad] = useState<Load>({ kind: 'loading' });

  useEffect(() => {
    let alive = true;
    void loadMine().then((outcome) => {
      if (!alive) return;
      setLoad(outcome.kind === 'open' ? { kind: 'open', services: outcome.services } : { kind: outcome.kind });
    });
    return () => {
      alive = false;
    };
  }, []);

  return (
    <section className={styles.card} aria-labelledby="my-services-heading">
      <h1 id="my-services-heading" className={styles.cardHeading}>My services</h1>
      {load.kind === 'loading' ? (
        <Loading label="Loading your services.">
          <SkeletonRows count={3} />
        </Loading>
      ) : null}
      {load.kind === 'unavailable' || load.kind === 'signed-out' ? (
        <p className={styles.notice} role="status">{load.kind === 'signed-out' ? SIGNED_OUT : LOAD_FAILED}</p>
      ) : null}
      {load.kind === 'open' ? (
        <ul className={styles.rows}>
          {load.services.map((service) => {
            const state = STATES[service.state];
            const attention = service.state === 'review-due';
            return (
              <li
                key={service.id}
                className={attention ? `${styles.row} ${styles.rowAttention}` : styles.row}
                data-attention={attention ? 'true' : undefined}
              >
                <div className={styles.rowBody}>
                  <strong className={styles.rowName}>{service.serviceName}</strong>
                  <p className={styles.rowDetail}>{service.detail}</p>
                </div>
                <StatusTag variant={state.variant}>{state.word}</StatusTag>
                <Link
                  className={attention ? `${styles.action} ${styles.actionPrimary}` : styles.action}
                  href={`/register/${encodeURIComponent(service.id)}/status`}
                  aria-label={`${state.action} ${service.serviceName}`}
                  data-el="REG-MYSERVICES-EDIT-LINK"
                >
                  {state.action}
                </Link>
              </li>
            );
          })}
        </ul>
      ) : null}
      <p className={styles.rowDetail}>A new service comes by invitation from your shift lead.</p>
    </section>
  );
}
