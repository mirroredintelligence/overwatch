'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Banner } from '@/components/ui/Banner';
import { recordChannelForDevice } from '@/lib/reporter/channel';
import styles from './Setup.module.css';

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
    <main className={styles.page}>
      <p className={styles.caption}>Step 4 of 5</p>
      <h1 className={styles.title}>Allow notifications</h1>
      <p>{`What we send: Capacity requests and booking requests for ${service}.`}</p>
      <p>What we never send: Patient names or details.</p>
      <p>You choose: Turn them off any time in Settings.</p>
      <p>When you allow, we record the date and this phone.</p>
      {denied ? (
        <p>
          <a href="/app/notifications-off">Notifications are off. See how to turn them on.</a>
        </p>
      ) : null}
      {textFailed ? <Banner tone="warning" title="We could not save that. Check your number again, then try once more." /> : null}
      <Button variant="primary" busy={busy} dataEl="ONB-NOTIF-ALLOW-BTN" onClick={allow}>
        Allow notifications
      </Button>
      <Button variant="neutral" dataEl="ONB-NOTIF-NOTNOW-BTN" onClick={useText}>
        Not now. Use text instead
      </Button>
    </main>
  );
}
