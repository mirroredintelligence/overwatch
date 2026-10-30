'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Banner } from '@/components/ui/Banner';
import { recordChannel } from '@/lib/reporter/channel';
import styles from '@/components/reporter/Reporter.module.css';

// Notifications are off (W37): the three steps on the phone, then a re-check of the browser's
// permission. Nothing here asks for permission; the reporter turns it on in the phone's settings.

export function NotificationsOff() {
  const router = useRouter();
  const [still, setStill] = useState(false);
  const [failed, setFailed] = useState(false);

  const recheck = () => {
    if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
      router.push('/app/settings');
      return;
    }
    setStill(true);
  };

  // Reached from Settings (signed in) or from set-up (no session yet): the session's route first, then
  // the phone's device.
  const chooseText = async () => {
    setFailed(false);
    if ((await recordChannel('text')) === 'ok') router.push('/setup/done?channel=text');
    else setFailed(true);
  };

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Notifications are off</h1>
      <p>We cannot alert you. Turn them on in your phone settings, or switch to text.</p>
      <ol>
        <li>Open your phone Settings</li>
        <li>Find DIUCS capacity</li>
        <li>Turn Notifications on</li>
      </ol>
      {still ? <p role="status">Notifications are still off.</p> : null}
      {failed ? <Banner tone="warning" title="We could not change how we contact you. Check your number again, then try once more." /> : null}
      <Button variant="neutral" dataEl="REP-NOTIF-TEXT-BTN" onClick={() => void chooseText()}>
        Use text instead
      </Button>
      <Button variant="primary" dataEl="REP-NOTIF-RECHECK-BTN" onClick={recheck}>
        I have turned them on
      </Button>
    </main>
  );
}
