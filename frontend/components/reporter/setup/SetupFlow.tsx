'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { type CheckResult, CodeEntry } from '@/components/reporter/CodeEntry';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { bffRequest } from '@/lib/reporter/browser';
import { type Invitation, parseInvitation } from '@/lib/reporter/model';
import styles from './Setup.module.css';

// The first half of reporter set-up (W33): welcome, number check, the 6-digit text code and how
// the reporter is contacted. Each step is its own page state (?step=); the invitation token rides in
// the address, and the masked number is the only phone number the page ever shows.

export type SetupStep = 'welcome' | 'number' | 'code' | 'channel';
export type Channel = 'app' | 'text' | 'email';

const CHANNELS: { value: Channel; label: string; hint: string }[] = [
  { value: 'app', label: 'App notification', hint: 'Recommended. A notification opens the app. Needs adding to your home screen.' },
  { value: 'text', label: 'Text message', hint: 'A text with a link. Works on any phone.' },
  { value: 'email', label: 'Email', hint: 'An email with a link.' },
];

type Props = { step: SetupStep; invite: string };

export function SetupFlow({ step, invite }: Props) {
  const router = useRouter();
  const [invitation, setInvitation] = useState<Invitation | null>(null);
  const [unusable, setUnusable] = useState<'expired' | 'failed' | null>(null);

  useEffect(() => {
    let live = true;
    // An empty token is shown as expired by the render below, so nothing is requested for it.
    if (invite === '') return undefined;
    void bffRequest(`/api/bff/invitations/${encodeURIComponent(invite)}`).then((reply) => {
      if (!live) return;
      // The back end says "expired" (410) for every invitation it will not use; a failed check is not that.
      if (reply.status === 410) return setUnusable('expired');
      const parsed = reply.status === 200 ? parseInvitation(reply.body) : null;
      if (parsed === null) return setUnusable('failed');
      if (parsed.state !== 'valid') return setUnusable('expired');
      setInvitation(parsed);
    });
    return () => {
      live = false;
    };
  }, [invite]);

  if (unusable === 'failed') {
    return (
      <main className={styles.page}>
        <h1 className={styles.title}>We could not check this invitation</h1>
        <p>We could not check this invitation. Try again shortly.</p>
      </main>
    );
  }
  if (unusable === 'expired' || invite === '') {
    return (
      <main className={styles.page}>
        <h1 className={styles.title}>This invitation has expired</h1>
        <p>This invitation has expired. Ask the shift lead to send a new one.</p>
      </main>
    );
  }
  if (invitation === null) {
    return (
      <main className={styles.page}>
        <p role="status">Opening set-up</p>
      </main>
    );
  }

  const go = (query: string) => router.push(`/setup?${query}&invite=${encodeURIComponent(invite)}`);
  const toHomeScreen = () => router.push('/setup/home-screen');

  if (step === 'welcome') return <Welcome service={invitation.service} onStart={() => go('step=number')} />;
  if (step === 'number') return <NumberStep masked={invitation.maskedPhone} invite={invite} onSent={() => go('step=code')} />;
  if (step === 'code') {
    return (
      <CodeStep
        invite={invite}
        onVerified={() => (invitation.role === 'exec' ? toHomeScreen() : go('step=channel'))}
      />
    );
  }
  return (
    <ChannelStep
      invite={invite}
      onChosen={(channel) => (channel === 'app' ? toHomeScreen() : router.push(`/setup/done?channel=${channel}`))}
      onCheckNumberAgain={() => go('step=number')}
    />
  );
}

function Welcome({ service, onStart }: { service: string; onStart: () => void }) {
  return (
    <main className={styles.page}>
      <h1 className={styles.title}>{`Set up capacity reporting for ${service}`}</h1>
      <ol className={styles.steps}>
        <li>Check your number: 30 seconds</li>
        <li>Choose how we contact you: 1 minute</li>
        <li>Add to home screen: 1 minute, app only</li>
        <li>Allow notifications: app only</li>
        <li>Create a PIN: 30 seconds</li>
      </ol>
      <p>You can stop and come back to the link within 48 hours.</p>
      <Button variant="primary" dataEl="ONB-WELCOME-START-BTN" onClick={onStart}>
        Start
      </Button>
    </main>
  );
}

function NumberStep({ masked, invite, onSent }: { masked: string; invite: string; onSent: () => void }) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  const send = async () => {
    setBusy(true);
    setFailed(false);
    const reply = await bffRequest('/api/bff/identity/invitation-code', { method: 'POST', body: { invite } });
    setBusy(false);
    if (reply.status === 202) onSent();
    else setFailed(true);
  };

  return (
    <main className={styles.page}>
      <p className={styles.caption}>Step 1 of 5</p>
      <h1 className={styles.title}>Check your number</h1>
      <p>
        We will text a code to <strong>{masked}</strong>.
      </p>
      <p>Not your number? Ask the shift lead to send a new invitation.</p>
      {failed ? <Banner tone="warning" title="We could not send a code. Try again shortly." /> : null}
      <Button variant="primary" busy={busy} dataEl="ONB-CODE-SEND-BTN" onClick={send}>
        Send code
      </Button>
    </main>
  );
}

function CodeStep({ invite, onVerified }: { invite: string; onVerified: () => void }) {
  const sendCode = async () => (await bffRequest('/api/bff/identity/invitation-code', { method: 'POST', body: { invite } })).status === 202;

  const checkCode = async (code: string): Promise<CheckResult> => {
    const reply = await bffRequest('/api/bff/identity/invitation-code/verify', { method: 'POST', body: { invite, code } });
    const body = reply.body as { ok?: boolean; triesLeft?: number } | undefined;
    if (reply.status === 200 && body?.ok === true) return { ok: true };
    return { ok: false, triesLeft: typeof body?.triesLeft === 'number' ? body.triesLeft : null };
  };

  return (
    <main className={styles.page}>
      <p className={styles.caption}>Step 1 of 5</p>
      <h1 className={styles.title}>Enter the code</h1>
      <CodeEntry sendCode={sendCode} checkCode={checkCode} onVerified={onVerified} />
    </main>
  );
}

function ChannelStep({
  invite,
  onChosen,
  onCheckNumberAgain,
}: {
  invite: string;
  onChosen: (channel: Channel) => void;
  onCheckNumberAgain: () => void;
}) {
  const [channel, setChannel] = useState<Channel>('app');
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<'timed-out' | 'failed' | null>(null);

  // No one is signed in yet: the choice is recorded for this phone's device, which a text code
  // verified in the last ten minutes (the back end says no, 403, once that has lapsed).
  const save = async () => {
    setBusy(true);
    setFailed(null);
    const reply = await bffRequest('/api/bff/identity/channel', { method: 'POST', body: { channel } });
    setBusy(false);
    if (reply.status === 200 && (reply.body as { ok?: unknown } | undefined)?.ok === true) onChosen(channel);
    else setFailed(reply.status === 403 ? 'timed-out' : 'failed');
  };

  return (
    <main className={styles.page} data-invite-present={invite !== ''}>
      <p className={styles.caption}>Step 2 of 5</p>
      <h1 className={styles.title}>Choose how we contact you</h1>
      <fieldset className={styles.page}>
        <legend>How we contact you</legend>
        {CHANNELS.map((option) => (
          <label key={option.value} className={styles.option} data-el={`ONB-CHANNEL-${option.value.toUpperCase()}`}>
            <input
              type="radio"
              name="channel"
              value={option.value}
              checked={channel === option.value}
              onChange={() => setChannel(option.value)}
            />
            <span>
              {option.label}
              <span className={styles.hint}>{option.hint}</span>
            </span>
          </label>
        ))}
      </fieldset>
      <p>You can change this later in Settings.</p>
      {failed === 'failed' ? <Banner tone="warning" title="We could not save that. Try again." /> : null}
      {failed === 'timed-out' ? (
        <>
          <Banner tone="warning" title="That took too long. Check your number again to carry on." />
          <Button variant="neutral" dataEl="ONB-CHANNEL-RECHECK-BTN" onClick={onCheckNumberAgain}>
            Check my number again
          </Button>
        </>
      ) : null}
      <Button variant="primary" busy={busy} dataEl="ONB-CHANNEL-CONTINUE-BTN" onClick={save}>
        Continue
      </Button>
    </main>
  );
}
