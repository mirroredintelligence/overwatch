'use client';

import { useState, type FormEvent } from 'react';
import { ErrorSummary, type FieldError } from '@/components/lead/ErrorSummary';
import { TextField } from '@/components/forms/TextField';
import { Button } from '@/components/ui/Button';
import { operatorSend, useOperatorRead } from '@/lib/operator/browser';
import type { parseSupportTicket, parseTenantList } from '@/lib/operator/views';
import { useSubmitKey } from '@/lib/tenantAdmin/browser';
import { REASON_OPTIONS } from '@/lib/tenantAdmin/words';
import styles from '@/components/admin/admin.module.css';

// Asking to look into a tenant (TEN-083, DEC-1003): one active tenant, a reason code and a plain sentence that
// holds no name, number, postcode or patient. The restricted alphabet and the six-digit limit are said before
// the call and checked again by the back end. The tenant is a path of the call, not a field of the body.

type Tenants = ReturnType<typeof parseTenantList>;
type Ticket = ReturnType<typeof parseSupportTicket>;

const REASON_CHARS = /^[A-Za-z0-9 .,'&()+-]*$/;

export function NewSupportRequest({ initialTenant }: { initialTenant?: string }) {
  const tenants = useOperatorRead<Tenants>('/api/bff/platform/tenants');
  const [tenant, setTenant] = useState(initialTenant ?? '');
  const [code, setCode] = useState(REASON_OPTIONS[2]![0]);
  const [reason, setReason] = useState('');
  const [reference, setReference] = useState('');
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [failure, setFailure] = useState('');
  const [sent, setSent] = useState<Ticket | null>(null);
  const [busy, setBusy] = useState(false);
  const submitKey = useSubmitKey();
  const edit = (set: (v: string) => void) => (v: string) => {
    submitKey.fresh();
    set(v);
  };
  const problemOf = (field: string) => errors.find((e) => e.field === field)?.message ?? null;

  if (tenants.state.status === 'failed') {
    return (
      <main className={styles.page}>
        <h1 className={styles.title}>Ask for access</h1>
        <p role="alert" className={styles.problem}>
          We could not load the tenants.
        </p>
      </main>
    );
  }
  const active = tenants.state.status === 'ok' ? tenants.state.data.tenants.filter((t) => t.status === 'active') : [];
  // A tenant named by the address only counts when it is one of the active ones.
  const chosen = active.some((t) => t.id === tenant) ? tenant : '';

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setFailure('');
    const problems: FieldError[] = [];
    if (chosen === '') problems.push({ field: 'support-tenant', message: 'Choose a tenant.' });
    const text = reason.trim();
    if (text.length < 10) problems.push({ field: 'support-reason', message: 'Write at least 10 characters.' });
    else if (text.length > 200) problems.push({ field: 'support-reason', message: 'Write at most 200 characters.' });
    else if (!REASON_CHARS.test(text)) problems.push({ field: 'support-reason', message: "Use letters, digits and . , ' & ( ) + - only." });
    else if ((text.match(/\d/g) ?? []).length > 6) problems.push({ field: 'support-reason', message: 'Leave out long numbers: use at most six digits.' });
    if (reference.trim() !== '' && !/^[A-Za-z0-9-]{1,32}$/.test(reference.trim())) problems.push({ field: 'support-reference', message: 'Use letters, digits and hyphens only, up to 32.' });
    setErrors(problems);
    if (problems.length > 0) return;
    const body: Record<string, string> = { reasonCode: code, reason: text };
    if (reference.trim() !== '') body.reference = reference.trim();
    setBusy(true);
    const result = await operatorSend<Ticket>('POST', `/api/bff/platform/tenants/${chosen}/support-tickets`, body, submitKey.key());
    setBusy(false);
    if (result.ok) {
      submitKey.fresh();
      setSent(result.data);
      return;
    }
    setFailure(
      result.status === 409
        ? 'You already have a request open for this tenant. Finish it or let it lapse first.'
        : result.status === 404
          ? 'That tenant cannot be asked now. It may not be active.'
          : 'The request could not be sent. Try again.',
    );
  }

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Ask for access</h1>
      {sent !== null ? (
        <div role="status" className={styles.panel}>
          <p className={styles.ok}>Request sent. The tenant’s administrator will see it and, if they agree, give you a code.</p>
          <p className={styles.text}>
            <a className={styles.link} href={`/operator/support/tickets/${sent.id}`}>
              See the request
            </a>
          </p>
        </div>
      ) : null}
      <form className={styles.stack} onSubmit={submit} noValidate aria-label="Ask for access">
        <ErrorSummary errors={errors} />
        <div className={styles.selectLabel}>
          <label htmlFor="support-tenant">Tenant</label>
          <select id="support-tenant" className={styles.select} value={chosen} onChange={(event) => edit(setTenant)(event.target.value)} aria-invalid={problemOf('support-tenant') ? 'true' : undefined}>
            <option value="">Choose a tenant</option>
            {active.map((t) => (
              <option key={t.id} value={t.id}>
                {t.displayName}
              </option>
            ))}
          </select>
          {problemOf('support-tenant') ? <p className={styles.problem}>{problemOf('support-tenant')}</p> : null}
        </div>
        <div className={styles.selectLabel}>
          <label htmlFor="support-code">Type of problem</label>
          <select id="support-code" className={styles.select} value={code} onChange={(event) => edit(setCode)(event.target.value)}>
            {REASON_OPTIONS.map(([value, word]) => (
              <option key={value} value={value}>
                {word}
              </option>
            ))}
          </select>
        </div>
        <TextField
          id="support-reason"
          label="Reason in a sentence"
          value={reason}
          onChange={edit(setReason)}
          requirement="none"
          hint="Write a plain sentence of 10 to 200 characters. Do not put in a name, a phone number, a postcode or anything about a patient."
          error={problemOf('support-reason')}
          maxLength={400}
        />
        <TextField id="support-reference" label="Help-desk reference" value={reference} onChange={edit(setReference)} requirement="optional" error={problemOf('support-reference')} />
        {failure !== '' ? (
          <p role="alert" className={styles.problem}>
            {failure}
          </p>
        ) : null}
        <div className={styles.actions}>
          <Button variant="primary" type="submit" busy={busy} dataEl="OP-SUPPORT-SEND-BTN">
            Send the request
          </Button>
        </div>
      </form>
    </main>
  );
}
