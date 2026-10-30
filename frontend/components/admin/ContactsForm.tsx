'use client';

import { useState, type FormEvent } from 'react';
import { TextField } from '@/components/forms/TextField';
import { Button } from '@/components/ui/Button';
import { adminSend, useAdminRead, useSubmitKey } from '@/lib/tenantAdmin/browser';
import type { Overview } from './AdminOverview';
import styles from './admin.module.css';

// The organisation's contacts (TEN-076): one of each kind, saved one at a time, so a failure of one never
// loses the others. These are the organisation's own business lines and addresses, never a person's.

const KINDS: readonly [string, string][] = [
  ['coordination-phone', 'Coordination phone'],
  ['support-email', 'Support email'],
  ['shift-lead-escalation', 'Shift lead escalation'],
  ['clinical-safety-officer', 'Clinical safety officer'],
];

export function ContactsForm() {
  const { state } = useAdminRead<Overview>('/api/bff/tenant/overview');
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
      {state.status === 'ok'
        ? KINDS.map(([kind, name]) => <ContactKind key={kind} kind={kind} name={name} held={state.data.contacts.find((c) => c.kind === kind) ?? null} />)
        : null}
    </main>
  );
}

function ContactKind({ kind, name, held }: { kind: string; name: string; held: Overview['contacts'][number] | null }) {
  const [label, setLabel] = useState(held?.label ?? '');
  const [value, setValue] = useState(held?.value ?? '');
  const [errors, setErrors] = useState<{ label?: string; value?: string }>({});
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const submitKey = useSubmitKey();

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setMessage(null);
    const next: { label?: string; value?: string } = {};
    if (label.trim() === '') next.label = 'Enter a label.';
    if (value.trim() === '') next.value = 'Enter a number or address.';
    setErrors(next);
    if (next.label !== undefined || next.value !== undefined) return;
    setBusy(true);
    const result = await adminSend('PUT', '/api/bff/tenant/contacts', { kind, label: label.trim(), value: value.trim() }, submitKey.key());
    setBusy(false);
    if (result.ok) {
      submitKey.fresh();
      setMessage({ ok: true, text: 'Saved.' });
    } else setMessage({ ok: false, text: 'This contact could not be saved. Try again.' });
  }

  return (
    <form onSubmit={submit} noValidate>
      <fieldset className={styles.fieldset}>
        <legend className={styles.legend}>{name}</legend>
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
  );
}
