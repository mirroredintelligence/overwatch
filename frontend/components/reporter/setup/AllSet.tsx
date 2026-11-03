'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { ProviderShell } from '@/components/provider/ProviderShell';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { Loading, Skeleton } from '@/components/ui/Skeleton';
import { subscribeToPush } from '@/lib/push/subscribe';
import { bffRequest } from '@/lib/reporter/browser';
import { clock } from '@/lib/reporter/times';
import styles from './AllSet.module.css';

// The end of app set-up (W34, W8E). The subscription is saved here, after the reporter has signed in
// with the PIN (DEC-661): the back end saves one only for a signed-in person, for the device the session
// was made on. The browser's own permission decides whether to ask at all, the public key comes from the
// back end (it is the platform's, not a secret), and the subscription goes to the BFF and nowhere else:
// nothing is kept in the page or in storage, and the service worker holds none of it. The summary and
// the test notification come from the BFF; an answer that is not there is said so, never invented.
// The summary has no role or PIN state, so the card shows the four rows it does carry (brief gap 2).

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

  const nextUpdate = summary === null ? '' : clock(summary.nextUpdateDue);
  const rows: { label: string; value: string }[] =
    summary === null
      ? []
      : [
          { label: 'Service', value: summary.service },
          { label: 'We contact you by', value: CONTACT_LABEL[summary.contactBy] ?? 'Text message' },
          { label: 'Phone', value: summary.maskedPhone },
          { label: 'Next update due', value: nextUpdate || 'Not set' },
        ];

  return (
    <ProviderShell service={summary?.service ?? null} action={{ primary: { label: 'Open Overwatch', href: '/app' } }}>
      <section className={styles.card}>
        <div className={styles.mark} aria-hidden="true">
          <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
            <path d="M5 12.5l4.5 4.5L19 7.5" />
          </svg>
        </div>
        <h1 className={styles.title}>You are all set</h1>
        <p className={styles.lead}>
          {nextUpdate ? (
            <>
              Your first request arrives at <strong>{nextUpdate}</strong>. Answer it the way you will every time: pick the number and send.
            </>
          ) : (
            'Answer each request the way you will every time: pick the number and send.'
          )}
        </p>
      </section>

      {summary !== null ? (
        <dl className={styles.summary} data-el="ONB-DONE-SUMMARY">
          {rows.map((row) => (
            <div key={row.label} className={styles.row}>
              <dt className={styles.label}>{row.label}</dt>
              <dd className={styles.value}>{row.value}</dd>
            </div>
          ))}
        </dl>
      ) : summaryFailed ? null : (
        <div className={styles.summary}>
          <Loading label="Loading your set-up summary.">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className={styles.skeletonRow}>
                <Skeleton shape="line" width="38%" />
                <Skeleton shape="line" width="48%" />
              </div>
            ))}
          </Loading>
        </div>
      )}

      {saved === 'failed' ? <Banner tone="warning" title="We could not save your notification choice. Try again." /> : null}
      {summaryFailed ? <p className={styles.note}>We could not load your summary. Your set-up is saved.</p> : null}
      <p className={styles.note}>Change any of this later in Settings. Your shift lead can see that you are set up. They cannot see your PIN.</p>

      <div className={styles.test}>
        <Button variant="neutral" dataEl="ONB-DONE-TEST-BTN" onClick={sendTest}>
          Send me a test notification
        </Button>
        {testNotice !== null ? <p role="status">{testNotice}</p> : null}
      </div>
    </ProviderShell>
  );
}
