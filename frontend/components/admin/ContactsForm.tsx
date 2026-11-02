'use client';

import { useState, type FormEvent } from 'react';
import { TextField } from '@/components/forms/TextField';
import { Button } from '@/components/ui/Button';
import { adminSend, useAdminRead, useSubmitKey } from '@/lib/tenantAdmin/browser';
import type { Overview } from './AdminOverview';
import { Disclose } from './Disclose';
import styles from './admin.module.css';
import look from './Disclose.module.css';

// The organisation's contacts (TEN-076): one of each kind, saved one at a time, so a failure of one never
// loses the others. These are the organisation's own business lines and addresses, never a person's. Each kind
// is a row that says what is held (or that nothing is) and opens, one at a time, to its form.

const KINDS: readonly [string, string][] = [
  ['coordination-phone', 'Coordination phone'],
  ['support-email', 'Support email'],
  ['shift-lead-escalation', 'Shift lead escalation'],
  ['clinical-safety-officer', 'Clinical safety officer'],
];

// The back end takes a telephone number for these kinds and an email address for the others (the shape of each is
// checked there too). Staff are told to phone the shift lead, so that line is a number and not an address.
const PHONE_KINDS: ReadonlySet<string> = new Set(['coordination-phone', 'shift-lead-escalation']);
const PHONE_SHAPE = /^\+?[0-9][0-9 ]{5,18}[0-9]$/;
const EMAIL_SHAPE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

type Held = Overview['contacts'][number];

export function ContactsForm() {
  const { state } = useAdminRead<Overview>('/api/bff/tenant/overview');
  const [openKind, setOpenKind] = useState<string | null>(null);
  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Contacts</h1>
      <p className={styles.lede}>These are shown to your staff where a page tells them who to phone. Use your organisation’s own lines, not a person’s.</p>
      {state.status === 'loading' ? <p className={styles.muted}>Loading the contacts.</p> : null}
      {state.status === 'failed' ? (
        <p role="alert" className={styles.problem}>
          We could not load the contacts.
        </p>
      ) : null}
      {state.status === 'ok' ? (
        <ul className={look.list}>
          {KINDS.map(([kind, name]) => (
            <li key={kind}>
              <ContactKind
                kind={kind}
                name={name}
                held={state.data.contacts.find((c) => c.kind === kind) ?? null}
                open={openKind === kind}
                onToggle={() => setOpenKind((now) => (now === kind ? null : kind))}
              />
            </li>
          ))}
        </ul>
      ) : null}
    </main>
  );
}

function ContactKind({ kind, name, held, open, onToggle }: { kind: string; name: string; held: Held | null; open: boolean; onToggle: () => void }) {
  const [saved, setSaved] = useState<Held | null>(held);
  const [label, setLabel] = useState(held?.label ?? '');
  const [value, setValue] = useState(held?.value ?? '');
  const [errors, setErrors] = useState<{ label?: string; value?: string }>({});
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [round, setRound] = useState(0);
  const submitKey = useSubmitKey();
  const phone = PHONE_KINDS.has(kind);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setMessage(null);
    const next: { label?: string; value?: string } = {};
    if (label.trim() === '') next.label = 'Enter a label.';
    if (value.trim() === '') next.value = phone ? 'Enter a phone number.' : 'Enter an email address.';
    else if (!(phone ? PHONE_SHAPE : EMAIL_SHAPE).test(value.trim()))
      next.value = phone ? 'Enter a phone number, such as 01632 960001. An email address does not work here.' : 'Enter an email address, such as team@example.nhs.uk.';
    setErrors(next);
    if (next.label !== undefined || next.value !== undefined) return;
    setBusy(true);
    const result = await adminSend('PUT', '/api/bff/tenant/contacts', { kind, label: label.trim(), value: value.trim() }, submitKey.key());
    setBusy(false);
    if (result.ok) {
      submitKey.fresh();
      setSaved({ kind, label: label.trim(), value: value.trim() } as Held);
      setRound((n) => n + 1);
      setMessage({ ok: true, text: 'Saved.' });
    } else setMessage({ ok: false, text: 'This contact could not be saved. Try again.' });
  }

  return (
    <Disclose
      open={open}
      onToggle={onToggle}
      title={name}
      hint={
        saved === null ? (
          'Nothing is set yet.'
        ) : (
          <span key={round} className={round > 0 ? look.flash : undefined}>
            {saved.label} · {saved.value}
          </span>
        )
      }
      aside={
        <>
          <span className={saved === null ? `${look.tag} ${look.tagDashed}` : `${look.tag} ${look.tagOn}`}>{saved === null ? 'Not set' : 'Set'}</span>
          <span>{open ? 'Close' : saved === null ? 'Add' : 'Edit'}</span>
        </>
      }
    >
      <form onSubmit={submit} noValidate>
        <fieldset className={styles.fieldset}>
          <legend className={look.srOnly}>{name}</legend>
          <TextField
            id={`${kind}-label`}
            label="Label"
            value={label}
            onChange={(v) => {
              submitKey.fresh();
              setLabel(v);
            }}
            requirement="none"
            error={errors.label}
          />
          <TextField
            id={`${kind}-value`}
            label="Number or address"
            hint={phone ? 'A phone number. Staff are told to phone this line.' : 'An email address.'}
            value={value}
            onChange={(v) => {
              submitKey.fresh();
              setValue(v);
            }}
            requirement="none"
            error={errors.value}
          />
          {message !== null ? (
            <p role={message.ok ? 'status' : 'alert'} className={message.ok ? styles.ok : styles.problem}>
              {message.text}
            </p>
          ) : null}
          <div className={styles.actions}>
            <Button variant="secondary" type="submit" busy={busy}>
              {`Save ${name.toLowerCase()}`}
            </Button>
          </div>
        </fieldset>
      </form>
    </Disclose>
  );
}
