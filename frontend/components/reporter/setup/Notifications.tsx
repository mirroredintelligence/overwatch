'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { Banner } from '@/components/ui/Banner';
import { ProviderShell } from '@/components/provider/ProviderShell';
import { recordChannelForDevice } from '@/lib/reporter/channel';
import setupStyles from './Setup.module.css';
import styles from './Notifications.module.css';

// Step 4 of 5 (W34). Nothing is asked of the browser until Allow is pressed: consent first, then
// the browser's own prompt. The push subscription is saved on the all-set step, once the reporter
// has signed in (the back end saves a subscription only for a signed-in person).

export function Notifications({ service }: { service: string }) {
  const router = useRouter();
  const [denied, setDenied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [textFailed, setTextFailed] = useState(false);

  const allow = async () => {
    setBusy(true);
    const permission = await Notification.requestPermission();
    setBusy(false);
    if (permission === 'granted') {
      router.push('/setup/pin');
      return;
    }
    setDenied(true);
  };

  // No one is signed in yet in set-up: the choice is recorded for this phone's device.
  const useText = async () => {
    setTextFailed(false);
    if ((await recordChannelForDevice('text')) === 'ok') router.push('/setup/done?channel=text');
    else setTextFailed(true);
  };

  return (
    <ProviderShell
      step={4}
      action={{
        primary: { label: 'Allow notifications', onClick: allow, busy, disabled: busy },
        link: { label: 'Not now. Use text instead', onClick: useText },
      }}
    >
      <div className={styles.stack}>
        <p className={setupStyles.caption}>Step 4 of 5</p>
        <h1 className={setupStyles.title}>Turn on notifications</h1>
        <section className={styles.cards} aria-label="What notifications do">
          <div className={styles.card}>
            <span className={styles.icon} aria-hidden="true">
              ✓
            </span>
            <span className={styles.cardText}>
              <span className={styles.cardTitle}>What we send</span>
              <span className={styles.cardBody}>{`Capacity requests and booking requests for ${service}.`}</span>
            </span>
          </div>
          <div className={styles.card}>
            <span className={`${styles.icon} ${styles.iconOff}`} aria-hidden="true">
              ✕
            </span>
            <span className={styles.cardText}>
              <span className={styles.cardTitle}>What we never send</span>
              <span className={styles.cardBody}>Patient names or details.</span>
            </span>
          </div>
          <div className={styles.card}>
            <span className={styles.icon} aria-hidden="true">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M6 9a6 6 0 0 1 12 0c0 6 2 7 2 7H4s2-1 2-7M10 20a2 2 0 0 0 4 0" />
              </svg>
            </span>
            <span className={styles.cardText}>
              <span className={styles.cardTitle}>You choose</span>
              <span className={styles.cardBody}>Turn them off any time in Settings.</span>
            </span>
          </div>
        </section>
        <p className={styles.note}>When you allow, we record the date and this phone.</p>
        {denied ? (
          <p>
            <a href="/app/notifications-off">Notifications are off. See how to turn them on.</a>
          </p>
        ) : null}
        {textFailed ? <Banner tone="warning" title="We could not save that. Check your number again, then try once more." /> : null}
      </div>
    </ProviderShell>
  );
}
