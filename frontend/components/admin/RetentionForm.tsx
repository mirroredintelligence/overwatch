'use client';

import { useState, type FormEvent } from 'react';
import { ErrorSummary, type FieldError } from '@/components/lead/ErrorSummary';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { adminSend, useAdminRead, useSubmitKey } from '@/lib/tenantAdmin/browser';
import type { Overview } from './AdminOverview';
import styles from './admin.module.css';

// Data retention (TEN-076): how long each class of data is kept and what happens when the time is up. One rule
// per class, or the platform's defaults. A class with no rule is not left out: the form will not save until
// every class has an action, and says which is missing.

const CLASSES: readonly [string, string][] = [
  ['capacity-reports', 'Capacity reports'],
  ['bookings', 'Bookings'],
  ['case-audit', 'Case audit'],
  ['communications', 'Communications'],
  ['telemetry-raw', 'Telemetry raw'],
  ['telemetry-aggregates', 'Telemetry aggregates'],
  ['audit-chain', 'Audit chain'],
  ['safety-concerns', 'Safety concerns'],
];
const ACTIONS: readonly [string, string][] = [
  ['delete', 'Delete'],
  ['summarise', 'Keep a summary'],
  ['keep', 'Keep'],
];

type Rule = { days: string; action: string };

export function RetentionForm() {
  const { state } = useAdminRead<Overview>('/api/bff/tenant/overview');
  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Data retention</h1>
      <p className={styles.lede}>How long each kind of data is kept, and what happens to it when the time is up.</p>
      {state.status === 'loading' ? <p className={styles.muted}>Loading the retention rules.</p> : null}
      {state.status === 'failed' ? (
        <p role="alert" className={styles.problem}>
          We could not load the retention rules.
        </p>
      ) : null}
      {state.status === 'ok' ? <Rules held={state.data.retention} /> : null}
    </main>
  );
}

function Rules({ held }: { held: Overview['retention'] }) {
  const [rules, setRules] = useState<Record<string, Rule>>(() =>
    Object.fromEntries(CLASSES.map(([code]) => {
      const rule = held.find((r) => r.dataClass === code);
      return [code, { days: rule?.keepDays == null ? '' : String(rule.keepDays), action: rule?.action ?? '' }];
    })),
  );
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [asking, setAsking] = useState(false);
  const submitKey = useSubmitKey();

  function edit(code: string, change: Partial<Rule>) {
    submitKey.fresh();
    setRules((current) => ({ ...current, [code]: { ...current[code]!, ...change } }));
  }

  async function save(body: unknown, done: string, failed: string) {
    setBusy(true);
    setMessage(null);
    const result = await adminSend('PUT', '/api/bff/tenant/retention', body, submitKey.key());
    setBusy(false);
    if (result.ok) {
      submitKey.fresh();
      setMessage({ ok: true, text: done });
    } else setMessage({ ok: false, text: failed });
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const problems: FieldError[] = [];
    const wire = CLASSES.map(([code, name]) => {
      const rule = rules[code]!;
      if (rule.action === '') problems.push({ field: `action-${code}`, message: `Choose what happens to ${name}.` });
      if (rule.days.trim() !== '' && !/^[1-9]\d{0,5}$/.test(rule.days.trim())) problems.push({ field: `days-${code}`, message: 'Enter a whole number of days, 1 or more, or leave it empty.' });
      return { dataClass: code, keepDays: rule.days.trim() === '' ? null : Number(rule.days.trim()), action: rule.action };
    });
    setErrors(problems);
    if (problems.length > 0) return;
    void save({ rules: wire }, 'Retention rules saved.', 'The retention rules could not be saved. Try again.');
  }

  const problemOf = (field: string) => errors.find((e) => e.field === field)?.message;

  return (
    <form className={styles.stack} onSubmit={submit} noValidate aria-label="Retention rules">
      <ErrorSummary errors={errors} />
      <div className={styles.scroll}>
        <table className={styles.table}>
          <caption>Retention rules</caption>
          <thead>
            <tr>
              <th scope="col">Data</th>
              <th scope="col">Days to keep</th>
              <th scope="col">At the end</th>
            </tr>
          </thead>
          <tbody>
            {CLASSES.map(([code, name]) => (
              <tr key={code}>
                <th scope="row">{name}</th>
                <td>
                  <input
                    id={`days-${code}`}
                    className={styles.select}
                    type="number"
                    inputMode="numeric"
                    min={1}
                    aria-label={`Days to keep ${name}`}
                    aria-invalid={problemOf(`days-${code}`) ? 'true' : undefined}
                    value={rules[code]!.days}
                    onChange={(event) => edit(code, { days: event.target.value })}
                  />
                  {problemOf(`days-${code}`) ? <p className={styles.problem}>{problemOf(`days-${code}`)}</p> : null}
                </td>
                <td>
                  <select
                    id={`action-${code}`}
                    className={styles.select}
                    aria-label={`What happens to ${name}`}
                    aria-invalid={problemOf(`action-${code}`) ? 'true' : undefined}
                    value={rules[code]!.action}
                    onChange={(event) => edit(code, { action: event.target.value })}
                  >
                    <option value="">Choose</option>
                    {ACTIONS.map(([value, word]) => (
                      <option key={value} value={value}>
                        {word}
                      </option>
                    ))}
                  </select>
                  {problemOf(`action-${code}`) ? <p className={styles.problem}>{problemOf(`action-${code}`)}</p> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {message !== null ? (
        <p role={message.ok ? 'status' : 'alert'} className={message.ok ? styles.ok : styles.problem}>
          {message.text}
        </p>
      ) : null}
      <div className={styles.actions}>
        <Button variant="primary" type="submit" busy={busy} dataEl="ADMIN-RETENTION-SAVE-BTN">
          Save retention rules
        </Button>
        <Button variant="secondary" onClick={() => setAsking(true)} dataEl="ADMIN-RETENTION-DEFAULTS-BTN">
          Use the platform defaults
        </Button>
      </div>
      {asking ? (
        <Dialog title="Use the platform defaults?" sub="Every rule above is replaced by the platform's own." onClose={() => setAsking(false)}>
          <div className={styles.actions}>
            <Button
              variant="primary"
              busy={busy}
              onClick={() => {
                setAsking(false);
                void save({ useDefaults: true }, 'The platform defaults are in use.', 'The retention rules could not be saved. Try again.');
              }}
            >
              Use the defaults
            </Button>
            <Button variant="neutral" onClick={() => setAsking(false)}>
              Cancel
            </Button>
          </div>
        </Dialog>
      ) : null}
    </form>
  );
}
