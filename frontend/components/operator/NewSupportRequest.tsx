'use client';

import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { useRouter } from 'next/navigation';
import { ErrorSummary, type FieldError } from '@/components/lead/ErrorSummary';
import { TextField } from '@/components/forms/TextField';
import { Button } from '@/components/ui/Button';
import { Loading, SkeletonRows } from '@/components/ui/Skeleton';
import { operatorSend, useOperatorRead } from '@/lib/operator/browser';
import type { parseSupportTicket, parseTenantList } from '@/lib/operator/views';
import { organisationTypeWord } from '@/lib/operator/words';
import { useSubmitKey } from '@/lib/tenantAdmin/browser';
import { REASON_OPTIONS } from '@/lib/tenantAdmin/words';
import styles from './Support.module.css';

// Asking to look into an organisation (TEN-083, DEC-1003, board O5): a sheet that slides in from the right over
// the requests. It is a dialog: focus moves in, Tab stays inside, Escape and Close and Cancel go back to the
// requests. One live organisation, a reason code and a plain sentence that holds no name, number, postcode or
// patient. The restricted alphabet and the six-digit limit are said before the call and checked again by the
// back end. The organisation is a path of the call, not a field of the body.

type Tenants = ReturnType<typeof parseTenantList>;
type Ticket = ReturnType<typeof parseSupportTicket>;

const REASON_CHARS = /^[A-Za-z0-9 .,'&()+-]*$/;
const BACK = '/operator/support';
const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function NewSupportRequest({ initialTenant }: { initialTenant?: string }) {
  const router = useRouter();
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
  const sheet = useRef<HTMLElement>(null);
  const titleId = useId();
  const edit = (set: (v: string) => void) => (v: string) => {
    submitKey.fresh();
    set(v);
  };
  const problemOf = (field: string) => errors.find((e) => e.field === field)?.message ?? null;
  const close = () => router.push(BACK);

  // Focus moves into the sheet once, when it opens, and goes back to the opener when it closes.
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    sheet.current?.querySelector<HTMLElement>(FOCUSABLE)?.focus();
    return () => {
      opener?.focus?.();
    };
  }, []);

  function onKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === 'Escape') {
      event.stopPropagation();
      close();
      return;
    }
    if (event.key !== 'Tab' || sheet.current === null) return;
    const items = Array.from(sheet.current.querySelectorAll<HTMLElement>(FOCUSABLE));
    const first = items[0];
    const last = items[items.length - 1];
    if (first === undefined || last === undefined) return;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  const live = tenants.state.status === 'ok' ? tenants.state.data.tenants.filter((t) => t.status === 'active') : [];
  // An organisation named by the address only counts when it is one of the live ones.
  const chosen = live.some((t) => t.id === tenant) ? tenant : '';

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setFailure('');
    const problems: FieldError[] = [];
    if (chosen === '') problems.push({ field: 'support-tenant', message: 'Choose an organisation.' });
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
        ? 'You already have a request open for this organisation. Finish it or let it lapse first.'
        : result.status === 404
          ? 'That organisation cannot be asked now. It may not be live.'
          : 'The request could not be sent. Try again.',
    );
  }

  const reasonProblem = problemOf('support-reason');
  const referenceFields = (
    <TextField id="support-reference" label="Help-desk reference" value={reference} onChange={edit(setReference)} requirement="optional" error={problemOf('support-reference')} />
  );

  return (
    <>
      <div className={styles.scrim} aria-hidden="true" onClick={close} />
      <section ref={sheet} role="dialog" aria-modal="true" aria-labelledby={titleId} className={styles.sheet} onKeyDown={onKeyDown} data-el="OP-SUPPORT-SHEET">
        <div className={styles.sheetHead}>
          <h2 id={titleId} className={styles.sheetTitle}>
            Ask for access
          </h2>
          <button type="button" className={styles.close} aria-label="Close" onClick={close}>
            <span aria-hidden="true">×</span>
          </button>
        </div>
        <p className={styles.lede}>Choose a live organisation. Nothing opens until its administrator approves.</p>

        {tenants.state.status === 'loading' ? (
          <Loading label="Loading the organisations.">
            <SkeletonRows count={2} />
          </Loading>
        ) : null}
        {tenants.state.status === 'failed' ? (
          <div role="alert" className={styles.problem}>
            <p className={styles.problemText}>We could not load the organisations.</p>
            <Button variant="secondary" onClick={tenants.reload}>
              Try again
            </Button>
          </div>
        ) : null}
        {tenants.state.status === 'ok' && live.length === 0 ? <p className={styles.status}>No organisation is live yet, so there is no one to ask.</p> : null}

        {sent !== null ? (
          <div role="status" className={styles.sent}>
            <p className={styles.sentText}>Request sent. The organisation’s administrator will see it and, if they agree, give you a code.</p>
            <a className={styles.link} href={`/operator/support/tickets/${sent.id}`}>
              See the request
            </a>
          </div>
        ) : null}

        {tenants.state.status === 'ok' && live.length > 0 && sent === null ? (
          <form className={styles.sheetForm} onSubmit={submit} noValidate aria-label="Ask for access">
            <ErrorSummary errors={errors} />
            <fieldset id="support-tenant" className={styles.choices} role="radiogroup" aria-invalid={problemOf('support-tenant') ? 'true' : undefined}>
              <legend className={styles.choicesLegend}>Organisation</legend>
              {live.map((t) => {
                const nameId = `${titleId}-name-${t.id}`;
                const subId = `${titleId}-sub-${t.id}`;
                return (
                  <label key={t.id} className={styles.choice}>
                    <input type="radio" name="support-organisation" value={t.id} checked={chosen === t.id} onChange={() => edit(setTenant)(t.id)} aria-labelledby={nameId} aria-describedby={subId} />
                    <span id={nameId} className={styles.choiceName}>
                      {t.displayName}
                    </span>
                    <span id={subId} className={styles.choiceSub}>
                      {t.organisationType === null ? 'Live' : `${organisationTypeWord(t.organisationType)} · live`}
                    </span>
                  </label>
                );
              })}
              {problemOf('support-tenant') ? <p className={styles.fieldError}>{problemOf('support-tenant')}</p> : null}
            </fieldset>

            <div className={styles.field}>
              <label className={styles.fieldLabel} htmlFor="support-code">
                Type of problem
              </label>
              <select id="support-code" className={styles.select} value={code} onChange={(event) => edit(setCode)(event.target.value)}>
                {REASON_OPTIONS.map(([value, word]) => (
                  <option key={value} value={value}>
                    {word}
                  </option>
                ))}
              </select>
            </div>

            <div className={styles.field}>
              <label className={styles.fieldLabel} htmlFor="support-reason">
                Why, in a sentence
              </label>
              <p id="support-reason-hint" className={styles.fieldHint}>
                Write a plain sentence of 10 to 200 characters. Do not put in a name, a phone number, a postcode or anything about a patient.
              </p>
              <textarea
                id="support-reason"
                className={styles.textarea}
                value={reason}
                maxLength={400}
                rows={3}
                onChange={(event) => edit(setReason)(event.target.value)}
                aria-invalid={reasonProblem ? 'true' : undefined}
                aria-describedby={reasonProblem ? 'support-reason-hint support-reason-error' : 'support-reason-hint'}
              />
              {reasonProblem ? (
                <p id="support-reason-error" className={styles.fieldError}>
                  {reasonProblem}
                </p>
              ) : null}
            </div>

            {referenceFields}

            {failure !== '' ? (
              <p role="alert" className={styles.fieldError}>
                {failure}
              </p>
            ) : null}
            {busy ? (
              <p role="status" className={styles.status}>
                Sending the request.
              </p>
            ) : null}
            <div className={styles.sheetActions}>
              <Button variant="primary" type="submit" busy={busy} dataEl="OP-SUPPORT-SEND-BTN">
                Send the request
              </Button>
              <Button variant="neutral" onClick={close}>
                Cancel
              </Button>
            </div>
          </form>
        ) : null}

        {sent !== null || live.length === 0 || tenants.state.status !== 'ok' ? (
          <div className={styles.sheetActions}>
            <Button variant="neutral" onClick={close}>
              Cancel
            </Button>
          </div>
        ) : null}
      </section>
    </>
  );
}
