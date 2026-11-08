'use client';

import { useState, type FormEvent } from 'react';
import { TextField } from '@/components/forms/TextField';
import { Button } from '@/components/ui/Button';
import { adminSend, useAdminRead, useSubmitKey } from '@/lib/tenantAdmin/browser';
import type { Overview } from './AdminOverview';
import { Disclose } from './Disclose';
import { Loading, SkeletonRows } from '@/components/ui/Skeleton';
import styles from './admin.module.css';
import look from './Disclose.module.css';
import own from './ContactsForm.module.css';

// The organisation's contacts (TEN-076): one of each kind, saved one at a time, so a failure of one never
// loses the others. These are the organisation's own business lines and addresses, never a person's. Each kind
// is a row that says what is held (or that nothing is) and opens, one at a time, to its form. The line that is
// saved is shown beside the rows, as staff will see it on a page.

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

// A kind the service cannot go live without, said in its row until it is set.
const NEEDED_TO_GO_LIVE: ReadonlySet<string> = new Set(['coordination-phone', 'clinical-safety-officer']);
const UNSET_HINT: Readonly<Record<string, string>> = {
  'coordination-phone': 'A phone number. Needed to go live.',
  'support-email': 'Nothing is set yet.',
  'shift-lead-escalation': 'Staff are told to phone this line when a report is late.',
  'clinical-safety-officer': 'An email address. Needed to go live.',
};

type Held = Overview['contacts'][number];

export function ContactsForm() {
  const { state } = useAdminRead<Overview>('/api/bff/tenant/overview');
  const [openKind, setOpenKind] = useState<string | null>(null);
  // What this visit has saved, which overrides what the overview held when the page loaded.
  const [written, setWritten] = useState<Record<string, Held>>({});
  const heldFor = (kind: string): Held | null => {
    if (written[kind] !== undefined) return written[kind];
    return state.status === 'ok' ? (state.data.contacts.find((c) => c.kind === kind) ?? null) : null;
  };
  const openHeld = openKind === null ? null : heldFor(openKind);
  return (
    <main className={own.page}>
      <h1 className={styles.title}>Contacts</h1>
      <div className={own.layout}>
        <section aria-label="Contacts" className={own.list}>
          <p className={styles.lede}>These are shown to your staff where a page tells them who to phone. Use your organisation’s own lines, not a person’s.</p>
          {state.status === 'loading' ? <Loading label="Loading the contacts."><SkeletonRows count={3} /></Loading> : null}
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
                    held={heldFor(kind)}
                    open={openKind === kind}
                    onToggle={() => setOpenKind((now) => (now === kind ? null : kind))}
                    onSaved={(next) => setWritten((all) => ({ ...all, [kind]: next }))}
                  />
                </li>
              ))}
            </ul>
          ) : null}
        </section>
        <aside aria-label="How staff see it" className={own.preview}>
          <h2 className={own.previewTitle}>How staff will see it</h2>
          {openKind === null ? (
            <p className={styles.muted}>Open a contact to see how staff will see it.</p>
          ) : openHeld === null ? (
            <p className={styles.muted}>Nothing is set yet.</p>
          ) : (
            <p className={own.staffLine}>
              {openKind === 'shift-lead-escalation' ? 'Phone the shift lead: ' : null}
              <b>
                {openHeld.label}, {openHeld.value}
              </b>
              {openKind === 'shift-lead-escalation' ? '. No message is sent.' : null}
            </p>
          )}
          <p className={styles.muted}>The line you save is shown exactly like this. Nothing about a person is stored.</p>
        </aside>
      </div>
    </main>
  );
}

function ContactKind({
  kind,
  name,
  held,
  open,
  onToggle,
  onSaved,
}: {
  kind: string;
  name: string;
  held: Held | null;
  open: boolean;
  onToggle: () => void;
  onSaved: (next: Held) => void;
}) {
  const [label, setLabel] = useState(held?.label ?? '');
  const [value, setValue] = useState(held?.value ?? '');
  const [errors, setErrors] = useState<{ label?: string; value?: string }>({});
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [round, setRound] = useState(0);
  const submitKey = useSubmitKey();
  const phone = PHONE_KINDS.has(kind);
  const needed = NEEDED_TO_GO_LIVE.has(kind);
  const shortName = name.toLowerCase();

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
      onSaved({ kind, label: label.trim(), value: value.trim() } as Held);
      setRound((n) => n + 1);
      setMessage({ ok: true, text: 'Saved.' });
    } else setMessage({ ok: false, text: 'This contact could not be saved. Try again.' });
  }

  // Cancel closes the row and puts back what is saved, so nothing typed and not saved is kept.
  function cancel() {
    setLabel(held?.label ?? '');
    setValue(held?.value ?? '');
    setErrors({});
    setMessage(null);
    onToggle();
  }

  return (
    <Disclose
      open={open}
      onToggle={onToggle}
      title={name}
      hint={
        held === null ? (
          UNSET_HINT[kind]
        ) : (
          <span key={round} className={round > 0 ? look.flash : undefined}>
            {held.label} · {held.value}
          </span>
        )
      }
      aside={
        held !== null ? (
          <span className={`${look.tag} ${look.tagOn}`}>
            <span aria-hidden="true">● </span>
            <span>Set</span>
          </span>
        ) : needed ? (
          <span className={`${look.tag} ${look.tagClinical}`}>
            <span aria-hidden="true">◐ </span>
            <span>Needed to go live</span>
          </span>
        ) : (
          <span className={`${look.tag} ${look.tagDashed}`}>
            <span aria-hidden="true">○ </span>
            <span>Not set</span>
          </span>
        )
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
            label={phone ? 'Phone number' : 'Email address'}
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
          <div className={own.actions}>
            <Button variant="primary" type="submit" busy={busy}>
              Save{' '}<span className={look.srOnly}>{shortName}</span>
            </Button>
            <button type="button" className={own.cancel} onClick={cancel}>
              Cancel{' '}<span className={look.srOnly}>{shortName}</span>
            </button>
          </div>
        </fieldset>
      </form>
    </Disclose>
  );
}
