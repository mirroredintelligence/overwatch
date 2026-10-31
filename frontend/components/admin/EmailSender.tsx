'use client';

import { useState, type FormEvent } from 'react';
import { TextField } from '@/components/forms/TextField';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { adminSend, useAdminRead, useSubmitKey } from '@/lib/tenantAdmin/browser';
import type { Overview } from './AdminOverview';
import styles from './admin.module.css';

// The email channel (TEN-076, DEC-1007 item 3): the organisation manages its own email sender. The TEXT
// channel is the platform operator's and the screen says so and shows it read only. The reference of a
// channel's secret is never shown or typed here (the BFF drops it and refuses it): only whether the channel
// has sign-in details.

type Channel = Overview['channels'][number];
const ADDRESS = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function EmailSender() {
  const { state, reload } = useAdminRead<Overview>('/api/bff/tenant/overview');
  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Email sender</h1>
      {state.status === 'loading' ? <p className={styles.muted}>Loading the email sender.</p> : null}
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
    </main>
  );
}

function TextChannels({ channels }: { channels: Channel[] }) {
  return (
    <Card heading="Text messages">
      <p className={styles.text}>Text messages are set up by the platform operator. To change the number or the sender name, ask them.</p>
      {channels.map((channel) => (
        <p key={channel.id} className={styles.muted}>{`Sender name ${channel.senderLabel}`}</p>
      ))}
    </Card>
  );
}

function EmailChannels({ channels, onSaved }: { channels: Channel[]; onSaved: () => void }) {
  return (
    <Card heading="Email">
      {channels.length === 0 ? <p className={styles.text}>No email sender is set up yet.</p> : null}
      {channels.map((channel) => (
        <EmailForm key={channel.id} channel={channel} onSaved={onSaved} />
      ))}
      {channels.length === 0 ? <EmailForm channel={null} onSaved={onSaved} /> : null}
    </Card>
  );
}

function EmailForm({ channel, onSaved }: { channel: Channel | null; onSaved: () => void }) {
  const [sender, setSender] = useState(channel?.senderLabel ?? '');
  const [address, setAddress] = useState(channel?.fromAddress ?? '');
  const [display, setDisplay] = useState(channel?.fromDisplayName ?? '');
  const [errors, setErrors] = useState<{ sender?: string; address?: string }>({});
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const submitKey = useSubmitKey();
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

  return (
    <form className={styles.stack} onSubmit={submit} noValidate aria-label={channel === null ? 'Add an email sender' : 'Email sender'}>
      {channel !== null ? (
        <div className={styles.row}>
          <span className={channel.status === 'active' ? styles.tag : `${styles.tag} ${styles.tagDashed}`}>{channel.status === 'active' ? 'In use' : 'Stopped'}</span>
          <span className={styles.muted}>{channel.hasSecret ? 'Sign-in details: held' : 'Sign-in details: not set'}</span>
        </div>
      ) : null}
      <TextField id={`sender-${channel?.id ?? 'new'}`} label="Sender name" value={sender} onChange={touch(setSender)} requirement="none" error={errors.sender} />
      <TextField id={`address-${channel?.id ?? 'new'}`} label="From address" value={address} onChange={touch(setAddress)} requirement="none" error={errors.address} type="email" />
      <TextField id={`display-${channel?.id ?? 'new'}`} label="From display name" value={display} onChange={touch(setDisplay)} requirement="none" />
      {channel !== null ? (
        <dl className={styles.facts}>
          <dt>Sender</dt>
          <dd>{channel.senderLabel}</dd>
          <dt>Address</dt>
          <dd>{channel.fromAddress ?? '-'}</dd>
        </dl>
      ) : null}
      {message !== null ? (
        <p role={message.ok ? 'status' : 'alert'} className={message.ok ? styles.ok : styles.problem}>
          {message.text}
        </p>
      ) : null}
      <div className={styles.actions}>
        <Button variant="primary" type="submit" busy={busy} dataEl="ADMIN-EMAIL-SAVE-BTN">
          {channel === null ? 'Add email sender' : 'Save email sender'}
        </Button>
        {channel !== null && channel.status === 'active' ? (
          <Button variant="neutral" busy={busy} onClick={() => void send(body('retired'))}>
            Stop using this email sender
          </Button>
        ) : null}
      </div>
    </form>
  );
}
