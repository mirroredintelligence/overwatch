'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState, type ReactNode } from 'react';
import { type CheckResult, CodeEntry } from '@/components/reporter/CodeEntry';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { bffRequest } from '@/lib/reporter/browser';
import { type Invitation, parseInvitation } from '@/lib/reporter/model';
import { InvitationUnusable, SetupFrame, SetupLoading, StepHeading } from './InvitationLoader';
import styles from './Onboarding.module.css';

// The first half of reporter set-up (W33): welcome, number check, the 6-digit text code and how
// the reporter is contacted. Each step is its own page state (?step=); the invitation token rides in
// the address, and the masked number is the only phone number the page ever shows.

export type SetupStep = 'welcome' | 'number' | 'code' | 'channel';
export type Channel = 'app' | 'text' | 'email';

const CHANNELS: { value: Channel; label: string; hint: string }[] = [
  { value: 'app', label: 'App notification', hint: 'A notification opens the app. Needs adding to your home screen.' },
  { value: 'text', label: 'Text message', hint: 'A text with a link. Works on any phone.' },
  { value: 'email', label: 'Email', hint: 'An email with a link.' },
];

// The five set-up steps and what each takes (artboard R2, "Set-up welcome").
const WELCOME_STEPS = [
  { key: 'number', title: 'Check your number', hint: '30 sec' },
  { key: 'channel', title: 'Choose how we contact you', hint: '1 min' },
  { key: 'home', title: 'Add to home screen', hint: 'App only' },
  { key: 'notifications', title: 'Allow notifications', hint: 'App only' },
  { key: 'pin', title: 'Create a PIN', hint: '30 sec' },
] as const;

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

  if (unusable === 'failed') return <InvitationUnusable kind="failed" />;
  if (unusable === 'expired' || invite === '') return <InvitationUnusable kind="expired" />;
  if (invitation === null) {
    return (
      <SetupFrame view="checking">
        <SetupLoading label="Opening set-up" />
      </SetupFrame>
    );
  }

  const go = (query: string) => router.push(`/setup?${query}&invite=${encodeURIComponent(invite)}`);
  const toHomeScreen = () => router.push('/setup/home-screen');
  const frame = (progress: number, children: ReactNode) => (
    <SetupFrame service={invitation.service} step={progress} view={step}>
      {children}
    </SetupFrame>
  );

  if (step === 'welcome') return frame(0, <Welcome service={invitation.service} onStart={() => go('step=number')} />);
  if (step === 'number') {
    return frame(1, <NumberStep masked={invitation.maskedPhone} invite={invite} onSent={() => go('step=code')} />);
  }
  if (step === 'code') {
    return frame(
      1,
      <CodeStep
        invite={invite}
        masked={invitation.maskedPhone}
        onVerified={() => (invitation.role === 'exec' ? toHomeScreen() : go('step=channel'))}
      />,
    );
  }
  return frame(
    2,
    <ChannelStep
      invite={invite}
      onChosen={(channel) => (channel === 'app' ? toHomeScreen() : router.push(`/setup/done?channel=${channel}`))}
      onCheckNumberAgain={() => go('step=number')}
    />,
  );
}

function Welcome({ service, onStart }: { service: string; onStart: () => void }) {
  return (
    <>
      <div>
        <p className={styles.caption}>About 3 minutes</p>
        <StepHeading>{`Set up capacity reporting for ${service}`}</StepHeading>
      </div>
      <ol className={styles.steps} aria-label="Set-up steps">
        {WELCOME_STEPS.map((item, index) => (
          <li key={item.key} className={styles.step}>
            <span className={styles.stepNumber} aria-hidden="true">
              {index + 1}
            </span>
            <span className={styles.stepTitle}>{item.title}</span>
            <span className={styles.stepHint}>{item.hint}</span>
          </li>
        ))}
      </ol>
      <p className={styles.reassure}>You can stop at any point and come back to the link in your text. It works for 48 hours.</p>
      <div className={styles.action}>
        <Button variant="primary" dataEl="ONB-WELCOME-START-BTN" onClick={onStart}>
          Start
        </Button>
      </div>
    </>
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
    <>
      <p className={styles.caption}>Step 1 of 5 · Check your number</p>
      <div className={styles.card}>
        <StepHeading className={styles.cardTitle}>Check your number</StepHeading>
        <p className={styles.lead}>We will send a 6-digit code to this number.</p>
        <p className={styles.masked} data-el="ONB-MASKED-NUMBER">
          {masked}
        </p>
        <p className={styles.lead}>Not your number? Ask the shift lead to send a new invitation.</p>
        {failed ? <Banner tone="warning" title="We could not send a code. Try again shortly." /> : null}
      </div>
      <div className={styles.action}>
        <Button variant="primary" busy={busy} dataEl="ONB-CODE-SEND-BTN" onClick={send}>
          Send code
        </Button>
      </div>
    </>
  );
}

function CodeStep({ invite, masked, onVerified }: { invite: string; masked: string; onVerified: () => void }) {
  const sendCode = async () => (await bffRequest('/api/bff/identity/invitation-code', { method: 'POST', body: { invite } })).status === 202;

  const checkCode = async (code: string): Promise<CheckResult> => {
    const reply = await bffRequest('/api/bff/identity/invitation-code/verify', { method: 'POST', body: { invite, code } });
    const body = reply.body as { ok?: boolean; triesLeft?: number } | undefined;
    if (reply.status === 200 && body?.ok === true) return { ok: true };
    return { ok: false, triesLeft: typeof body?.triesLeft === 'number' ? body.triesLeft : null };
  };

  return (
    <>
      <p className={styles.caption}>Step 1 of 5 · Check your number</p>
      <div className={styles.summary}>
        <span className={styles.summaryTick} aria-hidden="true">
          ✓
        </span>
        <span className={styles.summaryText}>
          <strong>{masked}</strong>
          <span className={styles.summaryNote}>Code sent just now</span>
        </span>
      </div>
      <CodeEntry
        sendCode={sendCode}
        checkCode={checkCode}
        onVerified={onVerified}
        intro={
          <>
            <StepHeading className={styles.cardTitle}>Enter your code</StepHeading>
            <p className={styles.lead}>{`We sent a 6-digit code to ${masked}.`}</p>
          </>
        }
      >
        <details className={styles.disclosure}>
          <summary>This is not my number</summary>
          <div>Ask the shift lead to send a new invitation to the right number. Do not carry on.</div>
        </details>
      </CodeEntry>
    </>
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
    <>
      <p className={styles.caption} data-invite-present={invite !== ''}>
        Step 2 of 5
      </p>
      <StepHeading>How should we contact you?</StepHeading>
      <div role="radiogroup" aria-label="How we contact you" className={styles.options}>
        {CHANNELS.map((option) => (
          <label
            key={option.value}
            className={styles.option}
            data-chosen={channel === option.value ? 'true' : undefined}
            data-el={`ONB-CHANNEL-${option.value.toUpperCase()}`}
          >
            <input
              type="radio"
              name="channel"
              value={option.value}
              checked={channel === option.value}
              onChange={() => setChannel(option.value)}
            />
            <span className={styles.optionBody}>
              <span className={styles.optionHead}>
                <span className={styles.optionLabel}>{option.label}</span>
                {option.value === 'app' ? <span className={styles.recommended}>Recommended</span> : null}
              </span>
              <span className={styles.optionHint}>{option.hint}</span>
            </span>
          </label>
        ))}
      </div>
      <p className={styles.reassure}>You can change this later in Settings.</p>
      {failed === 'failed' ? <Banner tone="warning" title="We could not save that. Try again." /> : null}
      {failed === 'timed-out' ? (
        <>
          <Banner tone="warning" title="That took too long. Check your number again to carry on." />
          <Button variant="neutral" dataEl="ONB-CHANNEL-RECHECK-BTN" onClick={onCheckNumberAgain}>
            Check my number again
          </Button>
        </>
      ) : null}
      <div className={styles.action}>
        <Button variant="primary" busy={busy} dataEl="ONB-CHANNEL-CONTINUE-BTN" onClick={save}>
          Continue
        </Button>
      </div>
    </>
  );
}
