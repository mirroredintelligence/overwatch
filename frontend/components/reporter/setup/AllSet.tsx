'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { subscribeToPush } from '@/lib/push/subscribe';
import { bffRequest } from '@/lib/reporter/browser';
import { clock, inDays } from '@/lib/reporter/times';
import styles from './Setup.module.css';

// The end of app set-up (W34, W8E). The subscription is saved here, after the reporter has signed in
// with the PIN (DEC-661): the back end saves one only for a signed-in person, for the device the session
// was made on. The browser's own permission decides whether to ask at all, the public key comes from the
// back end (it is the platform's, not a secret), and the subscription goes to the BFF and nowhere else:
// nothing is kept in the page or in storage, and the service worker holds none of it. The summary and
// the test notification come from the BFF; an answer that is not there is said so, never invented.

const CONSENT_WORDING_VERSION = 'v1';

type Summary = { service: string; contactBy: string; maskedPhone: string; nextUpdateDue: string | null; textCodeInDays: number };

const CONTACT_LABEL: Record<string, string> = { app: 'App notification', text: 'Text message', email: 'Email' };

const TEST_MESSAGES: Record<number, string> = {
  409: 'No notification is saved for this phone yet. Allow notifications first.',
  429: 'You have sent a few test notifications. Try again in a few minutes.',
};

function readSummary(body: unknown): Summary | null {
  const v = body as Partial<Summary> | undefined;
  if (typeof v?.service !== 'string' || typeof v.contactBy !== 'string' || typeof v.maskedPhone !== 'string') return null;
  if (typeof v.textCodeInDays !== 'number') return null;
  return { service: v.service, contactBy: v.contactBy, maskedPhone: v.maskedPhone, nextUpdateDue: typeof v.nextUpdateDue === 'string' ? v.nextUpdateDue : null, textCodeInDays: v.textCodeInDays };
}

export function AllSet() {
  const router = useRouter();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [summaryFailed, setSummaryFailed] = useState(false);
  const [saved, setSaved] = useState<'pending' | 'saved' | 'failed'>('pending');
  const [testNotice, setTestNotice] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    void bffRequest('/api/bff/reporter/setup-summary').then((reply) => {
      if (!live) return;
      if (reply.status === 401) return router.replace('/app/pin');
      const read = reply.status === 200 ? readSummary(reply.body) : null;
      if (read !== null) setSummary(read);
      else setSummaryFailed(true);
      return undefined;
    });
    return () => {
      live = false;
    };
  }, [router]);

  useEffect(() => {
    let live = true;
    const save = async () => {
      if (typeof Notification === 'undefined' || Notification.permission !== 'granted') {
        if (live) setSaved('failed');
        return;
      }
      const key = await bffRequest('/api/bff/push/key');
      const publicKey = (key.body as { publicKey?: unknown } | undefined)?.publicKey;
      if (key.status !== 200 || typeof publicKey !== 'string') {
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
        if (live) setSaved(reply.status === 200 && (reply.body as { saved?: unknown } | undefined)?.saved === true ? 'saved' : 'failed');
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
    if (reply.status === 401) return router.replace('/app/pin');
    if (reply.status === 200 && (reply.body as { queued?: unknown } | undefined)?.queued === true) {
      return setTestNotice('A test notification is on its way.');
    }
    return setTestNotice(TEST_MESSAGES[reply.status] ?? 'We could not send a test notification. Try again.');
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
          <dd>{CONTACT_LABEL[summary.contactBy] ?? 'Text message'}</dd>
          <dt>Phone</dt>
          <dd>{summary.maskedPhone}</dd>
          <dt>Next update due</dt>
          <dd>{clock(summary.nextUpdateDue) || 'Not set'}</dd>
          <dt>Text code needed again</dt>
          <dd>{inDays(summary.textCodeInDays)}</dd>
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
