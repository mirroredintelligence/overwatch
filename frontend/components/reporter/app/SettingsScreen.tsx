'use client';

import { useRouter } from 'next/navigation';
import { type ReactNode, useEffect, useState } from 'react';
import { CoverUntil, NEEDS_DATE, type Until, untilBody } from '@/components/reporter/CoverUntil';
import { MOBILE_ERROR, MobileNumberField } from '@/components/reporter/MobileNumberField';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { Loading, Skeleton } from '@/components/ui/Skeleton';
import { StatusTag } from '@/components/ui/StatusTag';
import { isUkMobile } from '@/lib/forms/ukMobile';
import { bffRequest } from '@/lib/reporter/browser';
import { type ChannelWord, recordChannelForSession } from '@/lib/reporter/channel';
import { inDays } from '@/lib/reporter/times';
import styles from './SettingsScreen.module.css';

// Settings (W37, artboard B8). Every value is shown masked, from the back end. Signing out of this phone asks
// first, in the page, and then clears the session (the device stays this phone's). "Sign out of every phone"
// is a visible link to its own page.

type Settings = {
  channel: string;
  maskedPhone: string;
  maskedCover: string | null;
  reverifyInDays: number;
  otherDevices?: number;
};

const CHANNEL_LABEL: Record<string, string> = { app: 'App notification', text: 'Text message', email: 'Email' };

function notificationsOn(): boolean {
  return typeof Notification !== 'undefined' && Notification.permission === 'granted';
}

export function SettingsScreen() {
  const router = useRouter();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [failed, setFailed] = useState(false);
  const [coverOpen, setCoverOpen] = useState(false);
  const [cover, setCover] = useState('');
  const [until, setUntil] = useState<Until>('this-week');
  const [date, setDate] = useState('');
  const [channelOpen, setChannelOpen] = useState(false);
  const [channelChoice, setChannelChoice] = useState<ChannelWord>('app');
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
    const choice = untilBody(until, date);
    if (choice === null) return setCoverError(NEEDS_DATE);
    setCoverError(null);
    const reply = await bffRequest('/api/bff/reporter/cover', { method: 'POST', body: { phone: cover, ...choice } });
    // The number is not kept: the page holds it only until it is sent.
    setCover('');
    if (reply.status === 401) return router.replace('/app/pin');
    if (reply.status === 200) {
      setCoverOpen(false);
      const fresh = await bffRequest('/api/bff/reporter/settings');
      if (fresh.status === 200) setSettings(fresh.body as Settings);
      return undefined;
    }
    return setNotice('We could not save the cover number. Try again.');
  };

  const saveChannel = async () => {
    setNotice(null);
    const result = await recordChannelForSession(channelChoice);
    if (result === 'no-session') return router.replace('/app/pin');
    if (result !== 'ok') return setNotice('We could not change how we contact you. Try again.');
    setChannelOpen(false);
    const fresh = await bffRequest('/api/bff/reporter/settings');
    if (fresh.status === 200) setSettings(fresh.body as Settings);
    return undefined;
  };

  const signOut = async () => {
    const reply = await bffRequest('/api/bff/session', { method: 'DELETE' });
    if (reply.status === 204 || reply.status === 200) router.push('/app/pin');
    else setNotice('We could not sign you out. Try again.');
  };

  if (failed) return <main className={styles.page}><p>We could not load your settings. Try again shortly.</p></main>;
  if (settings === null) {
    return (
      <main className={styles.page}>
        <Loading label="Opening settings.">
          <Skeleton shape="title" width="40%" />
          <Skeleton shape="block" />
        </Loading>
      </main>
    );
  }

  const on = notificationsOn();
  const rows: { label: string; value: ReactNode }[] = [
    { label: 'Contact me by', value: CHANNEL_LABEL[settings.channel] ?? 'Text message' },
    { label: 'Notifications', value: on ? <StatusTag variant="live">On</StatusTag> : <StatusTag variant="todo">Off</StatusTag> },
    { label: 'Phone', value: settings.maskedPhone },
    { label: 'Cover number', value: settings.maskedCover ?? <StatusTag variant="paused">Not set</StatusTag> },
    { label: 'Text code needed again', value: inDays(settings.reverifyInDays) },
  ];

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Settings</h1>
      <dl className={styles.card} data-el="REP-SET-SUMMARY">
        {rows.map((row) => (
          <div key={row.label} className={styles.row}>
            <dt className={styles.label}>{row.label}</dt>
            <dd className={styles.value}>{row.value}</dd>
          </div>
        ))}
      </dl>
      {notice !== null ? <Banner tone="warning" title={notice} /> : null}

      {channelOpen ? (
        <fieldset className={styles.group}>
          <legend>How we contact you</legend>
          {(['app', 'text', 'email'] as const).map((word) => (
            <label key={word} className={styles.choice}>
              <input type="radio" name="channel" value={word} checked={channelChoice === word} onChange={() => setChannelChoice(word)} />
              {CHANNEL_LABEL[word]}
            </label>
          ))}
          <div className={styles.wide}>
            <Button variant="primary" dataEl="REP-SET-CHANNEL-SAVE-BTN" onClick={() => void saveChannel()}>
              Save how we contact me
            </Button>
          </div>
        </fieldset>
      ) : (
        <div className={styles.wide}>
          <Button variant="secondary" dataEl="REP-SET-CHANNEL-BTN" onClick={() => setChannelOpen(true)}>
            Change how we contact me
          </Button>
        </div>
      )}

      {coverOpen ? (
        <div className={styles.group}>
          <MobileNumberField label="Cover mobile number" value={cover} onChange={setCover} error={coverError} required dataEl="REP-SET-COVER-FIELD" />
          <CoverUntil until={until} date={date} onUntil={setUntil} onDate={setDate} name="cover-until" />
          <div className={styles.wide}>
            <Button variant="primary" dataEl="REP-SET-COVER-SAVE-BTN" onClick={() => void saveCover()}>
              Save cover number
            </Button>
          </div>
        </div>
      ) : (
        <div className={styles.wide}>
          <Button variant="secondary" dataEl="REP-SET-COVER-BTN" onClick={() => setCoverOpen(true)}>
            Add a cover number
          </Button>
        </div>
      )}

      {signOutAsk ? (
        <div role="group" aria-label="Sign out of this phone" className={styles.group}>
          <p className={styles.question}>Sign out of this phone?</p>
          <div className={styles.wide}>
            <Button variant="primary" dataEl="REP-SET-SIGNOUT-CONFIRM-BTN" onClick={() => void signOut()}>
              Confirm sign out
            </Button>
          </div>
          <div className={styles.wide}>
            <Button variant="neutral" dataEl="REP-SET-SIGNOUT-CANCEL-BTN" onClick={() => setSignOutAsk(false)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <div className={styles.wide}>
          <Button variant="neutral" dataEl="REP-SET-SIGNOUT-BTN" onClick={() => setSignOutAsk(true)}>
            Sign out of this phone
          </Button>
        </div>
      )}

      <a className={styles.every} href="/app/sign-out-all" data-el="REP-SET-SIGNOUT-ALL-LINK">
        Sign out of every phone
      </a>
    </main>
  );
}
