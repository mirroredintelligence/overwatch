'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { bffRequest } from '@/lib/reporter/browser';
import styles from '@/components/reporter/Reporter.module.css';

// Notifications are off (W37): the three steps on the phone, then a re-check of the browser's
// permission. Nothing here asks for permission; the reporter turns it on in the phone's settings.

export function NotificationsOff() {
  const router = useRouter();
  const [still, setStill] = useState(false);

  const recheck = () => {
    if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
      router.push('/app/settings');
      return;
    }
    setStill(true);
  };

  const chooseText = async () => {
    const reply = await bffRequest('/api/bff/reporter/channel', { method: 'POST', body: { channel: 'text' } });
    if (reply.status === 200 || reply.status === 204) router.push('/setup/done?channel=text');
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
      <Button variant="neutral" dataEl="REP-NOTIF-TEXT-BTN" onClick={() => void chooseText()}>
        Use text instead
      </Button>
      <Button variant="primary" dataEl="REP-NOTIF-RECHECK-BTN" onClick={recheck}>
        I have turned them on
      </Button>
    </main>
  );
}
