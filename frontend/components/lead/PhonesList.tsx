'use client';

import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { leadRead } from '@/lib/lead/browser';
import { listOf, textOf } from '@/lib/lead/answers';
import styles from './Lead.module.css';

// The phones the services report from, and the services on each (W43). A phone is shown as its last three
// digits only. A phone that holds more than three services is flagged, since more than three services on one
// phone slows replies.

export type PhoneRow = {
  phoneEnding: string;
  role: string;
  services: { id: string; name: string }[];
  channel: string;
  lastSeen: string;
};

const FLAG_ABOVE = 3;

function phonesFrom(body: unknown): PhoneRow[] {
  return listOf(body, 'phones').map((item) => {
    const row = item as Record<string, unknown>;
    return {
      phoneEnding: textOf(row.phoneEnding),
      role: textOf(row.role),
      services: listOf(row, 'services').map((s) => {
        const service = s as Record<string, unknown>;
        return { id: textOf(service.id), name: textOf(service.name) };
      }),
      channel: textOf(row.channel),
      lastSeen: textOf(row.lastSeen),
    };
  });
}

export function PhonesList() {
  const [phones, setPhones] = useState<PhoneRow[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void leadRead('/api/bff/lead/phones').then((result) => {
      if (cancelled) return;
      try {
        if (!result.ok) throw new Error('refused');
        setPhones(phonesFrom(result.body));
      } catch {
        setFailed(true);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Phones and services</h1>

      {failed ? (
        <p role="alert" className={styles.fieldError}>
          We could not load the phones.
        </p>
      ) : null}

      {!failed && phones === null ? <p className={styles.muted}>Loading the phones.</p> : null}

      {phones !== null ? (
        <div className={styles.scrollBox}>
          <table className={styles.table}>
            <caption className={styles.caption}>Phones and the services they report for</caption>
            <thead>
              <tr>
                <th scope="col">Phone</th>
                <th scope="col">Role</th>
                <th scope="col">Services</th>
                <th scope="col">Channel</th>
                <th scope="col">Last seen</th>
                <th scope="col">Flag</th>
              </tr>
            </thead>
            <tbody>
              {phones.map((phone) => (
                <tr key={phone.phoneEnding}>
                  <td>{`…${phone.phoneEnding}`}</td>
                  <td>{phone.role}</td>
                  <td>{phone.services.map((s) => s.name).join(', ')}</td>
                  <td>{phone.channel}</td>
                  <td>{phone.lastSeen}</td>
                  <td>{phone.services.length > FLAG_ABOVE ? `Holds ${phone.services.length} services` : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      <p className={styles.muted}>More than 3 services on one phone slows replies.</p>
      <div className={styles.actions}>
        <Button variant="primary" href="/lead/phones/move" dataEl="LEAD-PHONES-MOVE-BTN">
          Move a service
        </Button>
        <Button variant="secondary" href="/lead/services/new" dataEl="LEAD-PHONES-ADD-BTN">
          Add a service to a phone
        </Button>
      </div>
    </main>
  );
}
