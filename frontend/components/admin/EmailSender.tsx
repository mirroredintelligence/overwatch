'use client';

import { useId, useState, type FormEvent } from 'react';
import { TextField } from '@/components/forms/TextField';
import { Button } from '@/components/ui/Button';
import { Loading, SkeletonRows } from '@/components/ui/Skeleton';
import { StatusTag } from '@/components/ui/StatusTag';
import { adminSend, useAdminRead, useSubmitKey } from '@/lib/tenantAdmin/browser';
import type { Overview } from './AdminOverview';
import styles from './EmailSender.module.css';

// The email channel (TEN-076, DEC-1007 item 3): the organisation manages its own email sender. The TEXT
// channel is the platform operator's and the screen says so and shows it read only. The reference of a
// channel's secret is never shown or typed here (the BFF drops it and refuses it): only whether the channel
// has sign-in details. On board A6 (left half): the text card, then the email card with a choice between the
// organisation's own address and not set up. The shared sender is not offered: it has no back end yet.

type Channel = Overview['channels'][number];
const ADDRESS = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function EmailSender() {
  const { state, reload } = useAdminRead<Overview>('/api/bff/tenant/overview');
  return (
    <main className={styles.page}>
      <h1 className={styles.srOnly}>Email sender</h1>
      <section aria-label="Senders" className={styles.senders}>
        <h2 className={styles.heading}>Who messages come from</h2>
        {state.status === 'loading' ? <Loading label="Loading the email sender."><SkeletonRows count={3} /></Loading> : null}
        {state.status === 'failed' ? (
          <p role="alert" className={styles.problem}>
            We could not load the email sender.
          </p>
        ) : null}
        {state.status === 'ok' ? (
          <>
            <TextChannels channels={state.data.channels.filter((c) => c.kind === 'sms')} />
            <EmailChannels channels={state.data.channels.filter((c) => c.kind === 'email')} onSaved={reload} />
          </>
        ) : null}
      </section>
    </main>
  );
}

function TextChannels({ channels }: { channels: Channel[] }) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className={styles.card}>
      <div className={styles.cardHead}>
        <h3 id={headingId} className={styles.cardTitle}>
          Text messages
        </h3>
        {channels.length > 0 ? <StatusTag variant="live">Using the shared line</StatusTag> : null}
      </div>
      <p className={styles.text}>
        Texts go out from Overwatch&apos;s shared line until your organisation has its own number. People cannot reply by text yet. To change this, ask the
        platform team.
      </p>
    </section>
  );
}

function EmailChannels({ channels, onSaved }: { channels: Channel[]; onSaved: () => void }) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className={`${styles.card} ${styles.cardEmail}`}>
      <h3 id={headingId} className={styles.cardTitle}>
        Email
      </h3>
      {channels.map((channel) => (
        <EmailForm key={channel.id} channel={channel} onSaved={onSaved} />
      ))}
      {channels.length === 0 ? <EmailForm channel={null} onSaved={onSaved} /> : null}
    </section>
  );
}

function EmailForm({ channel, onSaved }: { channel: Channel | null; onSaved: () => void }) {
  const [sender, setSender] = useState(channel?.senderLabel ?? '');
  const [address, setAddress] = useState(channel?.fromAddress ?? '');
  const [display, setDisplay] = useState(channel?.fromDisplayName ?? '');
  const [errors, setErrors] = useState<{ sender?: string; address?: string }>({});
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [chosen, setChosen] = useState(false);
  const submitKey = useSubmitKey();
  const radioId = useId();
  const hintId = useId();
  // The own address is the one choice on offer: it is in force once the organisation has a sender, and
  // otherwise it is in force once the person picks it. Not picked, the email sender is not set up.
  const own = channel !== null || chosen;
  const touch = (set: (v: string) => void) => (v: string) => {
    submitKey.fresh();
    set(v);
  };

  function body(status?: 'retired') {
    const out: Record<string, string> = { kind: 'email', senderLabel: sender.trim() };
    if (address.trim() !== '') out.fromAddress = address.trim();
    if (display.trim() !== '') out.fromDisplayName = display.trim();
    if (status !== undefined) out.status = status;
    return out;
  }

  async function send(payload: Record<string, string>) {
    if (busy) return;
    setBusy(true);
    setMessage(null);
    const result =
      channel === null
        ? await adminSend('POST', '/api/bff/tenant/channels', payload, submitKey.key())
        : await adminSend('PUT', `/api/bff/tenant/channels/${channel.id}`, payload, submitKey.key());
    setBusy(false);
    if (result.ok) {
      submitKey.fresh();
      setMessage({ ok: true, text: 'Email sender saved.' });
      onSaved();
    } else setMessage({ ok: false, text: 'The email sender could not be saved. Try again.' });
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const next: { sender?: string; address?: string } = {};
    if (sender.trim() === '') next.sender = 'Enter a sender name.';
    if (address.trim() !== '' && !ADDRESS.test(address.trim())) next.address = 'Enter an email address, for example name@example.test.';
    setErrors(next);
    if (next.sender !== undefined || next.address !== undefined) return;
    void send(body());
  }

  const status =
    channel === null ? { variant: 'todo' as const, word: 'Not set up' } : channel.status === 'active' ? { variant: 'live' as const, word: 'In use' } : { variant: 'paused' as const, word: 'Stopped' };

  return (
    <form className={styles.form} onSubmit={submit} noValidate aria-label={channel === null ? 'Add an email sender' : 'Email sender'}>
      <div className={styles.cardHead}>
        <StatusTag variant={status.variant}>{status.word}</StatusTag>
        {channel !== null ? <span className={styles.muted}>{channel.hasSecret ? 'Sign-in details: held' : 'Sign-in details: not set'}</span> : null}
      </div>
      <div className={own ? `${styles.option} ${styles.optionOn}` : styles.option}>
        <input
          id={radioId}
          type="radio"
          name={`sender-choice-${channel?.id ?? 'new'}`}
          className={styles.radio}
          checked={own}
          onChange={() => setChosen(true)}
          aria-describedby={hintId}
        />
        <div className={styles.optionText}>
          <label htmlFor={radioId} className={styles.optionTitle}>
            Use your own address
          </label>
          <p id={hintId} className={styles.optionHint}>
            Choose the sender name and address. We check it before it is used.
          </p>
        </div>
      </div>
      {own ? (
        <>
          <TextField id={`sender-${channel?.id ?? 'new'}`} label="Sender name" value={sender} onChange={touch(setSender)} requirement="none" error={errors.sender} />
          <TextField
            id={`address-${channel?.id ?? 'new'}`}
            label="From address"
            value={address}
            onChange={touch(setAddress)}
            requirement="none"
            error={errors.address}
            type="email"
          />
          <TextField id={`display-${channel?.id ?? 'new'}`} label="From display name" value={display} onChange={touch(setDisplay)} requirement="none" />
          {message !== null ? (
            <p role={message.ok ? 'status' : 'alert'} className={message.ok ? styles.ok : styles.problem}>
              {message.text}
            </p>
          ) : null}
          <div className={styles.actions}>
            {channel !== null && channel.status === 'active' ? (
              <Button variant="neutral" busy={busy} onClick={() => void send(body('retired'))}>
                Stop using this email sender
              </Button>
            ) : null}
            <Button variant="primary" type="submit" busy={busy} dataEl="ADMIN-EMAIL-SAVE-BTN">
              Save choice
            </Button>
          </div>
        </>
      ) : null}
    </form>
  );
}
