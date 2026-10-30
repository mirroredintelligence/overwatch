'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { MOBILE_ERROR, MobileNumberField } from '@/components/reporter/MobileNumberField';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { isUkMobile } from '@/lib/forms/ukMobile';
import { bffRequest } from '@/lib/reporter/browser';
import styles from '@/components/reporter/Reporter.module.css';

// Settings (W37). Every value is shown masked, from the back end. Signing out of this phone asks
// first, in the page, and then clears the session (the device stays this phone's).

type Settings = {
  channel: string;
  maskedPhone: string;
  maskedCover: string | null;
  reverifyInDays: number;
  otherDevices?: number;
};

const CHANNEL_LABEL: Record<string, string> = { app: 'App notification', text: 'Text message', email: 'Email' };

function notificationsState(): 'On' | 'Off' {
  return typeof Notification !== 'undefined' && Notification.permission === 'granted' ? 'On' : 'Off';
}

export function SettingsScreen() {
  const router = useRouter();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [failed, setFailed] = useState(false);
  const [coverOpen, setCoverOpen] = useState(false);
  const [cover, setCover] = useState('');
  const [coverError, setCoverError] = useState<string | null>(null);
  const [signOutAsk, setSignOutAsk] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    void bffRequest('/api/bff/reporter/settings').then((reply) => {
      if (!live) return;
      if (reply.status === 401) return router.replace('/app/pin');
      if (reply.status === 200) setSettings(reply.body as Settings);
      else setFailed(true);
    });
    return () => {
      live = false;
    };
  }, [router]);

  const saveCover = async () => {
    if (!isUkMobile(cover)) return setCoverError(MOBILE_ERROR);
    setCoverError(null);
    const reply = await bffRequest('/api/bff/reporter/cover', { method: 'POST', body: { phone: cover } });
    setCover('');
    if (reply.status === 200 || reply.status === 201) {
      setCoverOpen(false);
      const fresh = await bffRequest('/api/bff/reporter/settings');
      if (fresh.status === 200) setSettings(fresh.body as Settings);
      return undefined;
    }
    return setNotice('We could not save the cover number. Try again.');
  };

  const signOut = async () => {
    const reply = await bffRequest('/api/bff/session', { method: 'DELETE' });
    if (reply.status === 204 || reply.status === 200) router.push('/app/pin');
    else setNotice('We could not sign you out. Try again.');
  };

  if (failed) return <main className={styles.page}><p>We could not load your settings. Try again shortly.</p></main>;
  if (settings === null) return <main className={styles.page}><p role="status">Opening settings</p></main>;

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Settings</h1>
      <dl>
        <dt>Contact me by</dt>
        <dd>{CHANNEL_LABEL[settings.channel] ?? 'Text message'}</dd>
        <dt>Notifications</dt>
        <dd>{notificationsState()}</dd>
        <dt>Phone</dt>
        <dd>{settings.maskedPhone}</dd>
        <dt>Cover number</dt>
        <dd>{settings.maskedCover ?? 'Not set'}</dd>
        <dt>Text code needed again</dt>
        <dd>{`In ${settings.reverifyInDays} days`}</dd>
      </dl>
      {notice !== null ? <Banner tone="warning" title={notice} /> : null}

      <Button variant="neutral" dataEl="REP-SET-CHANNEL-BTN" onClick={() => router.push('/app/settings#contact')}>
        Change how we contact me
      </Button>

      {coverOpen ? (
        <div>
          <MobileNumberField label="Cover mobile number" value={cover} onChange={setCover} error={coverError} required dataEl="REP-SET-COVER-FIELD" />
          <Button variant="primary" dataEl="REP-SET-COVER-SAVE-BTN" onClick={() => void saveCover()}>
            Save cover number
          </Button>
        </div>
      ) : (
        <Button variant="neutral" dataEl="REP-SET-COVER-BTN" onClick={() => setCoverOpen(true)}>
          Add a cover number
        </Button>
      )}

      {signOutAsk ? (
        <div role="group" aria-label="Sign out of this phone">
          <p>Sign out of this phone?</p>
          <Button variant="primary" dataEl="REP-SET-SIGNOUT-CONFIRM-BTN" onClick={() => void signOut()}>
            Confirm sign out
          </Button>
          <Button variant="neutral" dataEl="REP-SET-SIGNOUT-CANCEL-BTN" onClick={() => setSignOutAsk(false)}>
            Cancel
          </Button>
        </div>
      ) : (
        <Button variant="neutral" dataEl="REP-SET-SIGNOUT-BTN" onClick={() => setSignOutAsk(true)}>
          Sign out of this phone
        </Button>
      )}
    </main>
  );
}
