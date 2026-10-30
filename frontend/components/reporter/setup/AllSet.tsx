'use client';

import { useEffect, useState } from 'react';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { subscribeToPush } from '@/lib/push/subscribe';
import { bffRequest } from '@/lib/reporter/browser';
import styles from './Setup.module.css';

// The end of app set-up (W34). The subscription is saved here, after the reporter has signed in
// with the PIN, because the back end saves one only for a signed-in person. The summary and the
// test notification come from the BFF; an answer that is not there is said so, never invented.

const CONSENT_WORDING_VERSION = 'v1';

type Summary = { service: string; contactBy: string; maskedPhone: string; nextUpdateDue: string; textCodeInDays: number };

export function AllSet() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [summaryFailed, setSummaryFailed] = useState(false);
  const [saved, setSaved] = useState<'pending' | 'saved' | 'failed'>('pending');
  const [testNotice, setTestNotice] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    void bffRequest('/api/bff/reporter/setup-summary').then((reply) => {
      if (!live) return;
      const body = reply.body as Summary | undefined;
      if (reply.status === 200 && body && typeof body.service === 'string') setSummary(body);
      else setSummaryFailed(true);
    });
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    let live = true;
    const save = async () => {
      if (typeof Notification === 'undefined' || Notification.permission !== 'granted') {
        if (live) setSaved('failed');
        return;
      }
      const key = await bffRequest('/api/bff/push/key');
      const publicKey = (key.body as { publicKey?: unknown } | undefined)?.publicKey;
      if (typeof publicKey !== 'string') {
        if (live) setSaved('failed');
        return;
      }
      try {
        const registration = await navigator.serviceWorker.ready;
        const subscription = await subscribeToPush(registration, publicKey);
        const reply = await bffRequest('/api/bff/push/subscriptions', {
          method: 'POST',
          body: { subscription, consentWordingVersion: CONSENT_WORDING_VERSION },
        });
        if (live) setSaved(reply.status === 200 ? 'saved' : 'failed');
      } catch {
        if (live) setSaved('failed');
      }
    };
    void save();
    return () => {
      live = false;
    };
  }, []);

  const sendTest = async () => {
    const reply = await bffRequest('/api/bff/push/test', { method: 'POST', body: {} });
    setTestNotice(reply.status === 200 ? 'A test notification is on its way.' : 'We could not send a test notification. Try again.');
  };

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>All set</h1>
      {saved === 'failed' ? (
        <Banner tone="warning" title="We could not save your notification choice. Try again." />
      ) : null}
      {summaryFailed ? <p>We could not load your summary. Your set-up is saved.</p> : null}
      {summary !== null ? (
        <dl>
          <dt>Service</dt>
          <dd>{summary.service}</dd>
          <dt>Contact by</dt>
          <dd>{summary.contactBy}</dd>
          <dt>Phone</dt>
          <dd>{summary.maskedPhone}</dd>
          <dt>Next update due</dt>
          <dd>{summary.nextUpdateDue}</dd>
          <dt>Text code needed again</dt>
          <dd>{`In ${summary.textCodeInDays} days`}</dd>
        </dl>
      ) : null}
      {testNotice !== null ? <p role="status">{testNotice}</p> : null}
      <Button variant="neutral" dataEl="ONB-DONE-TEST-BTN" onClick={sendTest}>
        Send me a test notification
      </Button>
      <a href="/app" className={styles.title}>
        Go to the app
      </a>
    </main>
  );
}
