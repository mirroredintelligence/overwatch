'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { loadMine, type MyService } from '@/lib/register/browser';
import styles from './register.module.css';

// My services (W26): one row per service the reporter has, its state as a word, and an Edit link to
// its status page. A new service comes by invitation from the shift lead, never from here.

const STATE_WORDS: Record<MyService['state'], string> = {
  active: 'Active',
  'pending-approval': 'Pending approval',
  'review-due': 'Review due',
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
    <div className={styles.stack}>
      <p className={styles.product}>DIUCS capacity</p>
      <h1 className={styles.heading}>My services</h1>
      {load.kind === 'loading' ? <p className={styles.text}>Loading your services.</p> : null}
      {load.kind === 'unavailable' || load.kind === 'signed-out' ? (
        <p className={styles.notice} role="status">{load.kind === 'signed-out' ? SIGNED_OUT : LOAD_FAILED}</p>
      ) : null}
      {load.kind === 'open' ? (
        <ul className={styles.rows}>
          {load.services.map((service) => (
            <li key={service.id} className={styles.row}>
              <div className={styles.rowHead}>
                <span className={styles.rowTitle}>{service.serviceName}</span>
                <span className={service.state === 'active' ? styles.complete : styles.attention}>{STATE_WORDS[service.state]}</span>
              </div>
              <p className={styles.note}>{service.detail}</p>
              <Link className={styles.changeLink} href={`/register/${encodeURIComponent(service.id)}/status`} aria-label={`Edit ${service.serviceName}`} data-el="REG-MYSERVICES-EDIT-LINK">
                Edit
              </Link>
            </li>
          ))}
        </ul>
      ) : null}
      <p className={styles.note}>To add a service, ask the shift lead. New services are added by invitation and checked.</p>
    </div>
  );
}
