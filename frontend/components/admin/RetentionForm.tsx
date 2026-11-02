'use client';

import { useState, type FormEvent } from 'react';
import { ErrorSummary, type FieldError } from '@/components/lead/ErrorSummary';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { adminSend, useAdminRead, useSubmitKey } from '@/lib/tenantAdmin/browser';
import type { Overview } from './AdminOverview';
import { Disclose } from './Disclose';
import { Loading, SkeletonRows } from '@/components/ui/Skeleton';
import styles from './admin.module.css';
import look from './Disclose.module.css';

// Data retention (TEN-076): how long each class of data is kept and what happens when the time is up. One rule
// per class, or the platform's defaults. A class with no rule is not left out: the form will not save until
// every class has an action, and says which is missing. The page leads with one answer (the defaults, custom
// rules, or some kinds still without one) and the schedule as chips; the table to change it opens on request.

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
type Held = Overview['retention'];

// The platform's own schedule (DEC-271, [ASSUMED]): what "Use the platform defaults" stores. It is here only to say
// whether the rules held are those defaults; the back end is the one that stores them.
const DEFAULTS: Held = [
  { dataClass: 'capacity-reports', keepDays: 730, action: 'summarise' },
  { dataClass: 'bookings', keepDays: 730, action: 'delete' },
  { dataClass: 'case-audit', keepDays: 2555, action: 'delete' },
  { dataClass: 'communications', keepDays: 730, action: 'delete' },
  { dataClass: 'telemetry-raw', keepDays: 90, action: 'delete' },
  { dataClass: 'telemetry-aggregates', keepDays: 730, action: 'delete' },
  { dataClass: 'audit-chain', keepDays: null, action: 'keep' },
  { dataClass: 'safety-concerns', keepDays: null, action: 'keep' },
];

/** "2 years", "90 days": how long, in words a person would say. */
function spanWord(days: number): string {
  if (days % 365 === 0) return days === 365 ? '1 year' : `${days / 365} years`;
  return days === 1 ? '1 day' : `${days} days`;
}

/** What happens to a class, in words: "2 years, then summarised", "kept, no time limit". */
function ruleWord(rule: Held[number]): string {
  if (rule.action === 'keep') return rule.keepDays === null ? 'kept, no time limit' : `kept for ${spanWord(rule.keepDays)}`;
  const then = rule.action === 'summarise' ? 'summarised' : 'deleted';
  return rule.keepDays === null ? `${then} at the end` : `${spanWord(rule.keepDays)}, then ${then}`;
}

function sameSchedule(a: Held, b: Held): boolean {
  return a.length === b.length && b.every((rule) => a.some((r) => r.dataClass === rule.dataClass && r.keepDays === rule.keepDays && r.action === rule.action));
}

export function RetentionForm() {
  const { state } = useAdminRead<Overview>('/api/bff/tenant/overview');
  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Data retention</h1>
      <p className={styles.lede}>How long each kind of data is kept, and what happens to it when the time is up.</p>
      {state.status === 'loading' ? <Loading label="Loading the retention rules."><SkeletonRows count={3} /></Loading> : null}
      {state.status === 'failed' ? (
        <p role="alert" className={styles.problem}>
          We could not load the retention rules.
        </p>
      ) : null}
      {state.status === 'ok' ? <Rules held={state.data.retention} /> : null}
    </main>
  );
}

function toForm(held: Held): Record<string, Rule> {
  return Object.fromEntries(
    CLASSES.map(([code]) => {
      const rule = held.find((r) => r.dataClass === code);
      return [code, { days: rule?.keepDays == null ? '' : String(rule.keepDays), action: rule?.action ?? '' }];
    }),
  );
}

function Rules({ held: first }: { held: Held }) {
  const [held, setHeld] = useState<Held>(first);
  const [rules, setRules] = useState<Record<string, Rule>>(() => toForm(first));
  const [open, setOpen] = useState(false);
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [asking, setAsking] = useState(false);
  const submitKey = useSubmitKey();

  function edit(code: string, change: Partial<Rule>) {
    submitKey.fresh();
    setRules((current) => ({ ...current, [code]: { ...current[code]!, ...change } }));
  }

  async function save(body: unknown, done: string, failed: string, stored: Held) {
    setBusy(true);
    setMessage(null);
    const result = await adminSend('PUT', '/api/bff/tenant/retention', body, submitKey.key());
    setBusy(false);
    if (result.ok) {
      submitKey.fresh();
      setHeld(stored);
      setRules(toForm(stored));
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
    void save({ rules: wire }, 'Retention rules saved.', 'The retention rules could not be saved. Try again.', wire as Held);
  }

  const problemOf = (field: string) => errors.find((e) => e.field === field)?.message;
  const missing = CLASSES.filter(([code]) => !held.some((r) => r.dataClass === code));
  const state =
    missing.length === CLASSES.length
      ? 'No retention rules are set yet'
      : missing.length > 0
        ? `${CLASSES.length - missing.length} of ${CLASSES.length} kinds of data have a rule`
        : sameSchedule(held, DEFAULTS)
          ? 'The platform defaults are in use'
          : 'Your own rules are in use';

  return (
    <>
      <section className={look.lead} aria-label="Retention at a glance">
        <p className={look.leadState}>{state}</p>
        <ul className={look.chips}>
          {CLASSES.map(([code, name], index) => {
            const rule = held.find((r) => r.dataClass === code);
            return (
              <li key={code} className={rule === undefined ? `${look.chip} ${look.tagDashed}` : look.chip} style={{ animationDelay: `${index * 30}ms` }}>
                <strong>{name}:</strong> {rule === undefined ? 'not set' : ruleWord(rule)}
              </li>
            );
          })}
        </ul>
        {message !== null ? (
          <p role={message.ok ? 'status' : 'alert'} className={message.ok ? styles.ok : styles.problem}>
            {message.text}
          </p>
        ) : null}
        <div className={look.leadActions}>
          <Button variant="secondary" onClick={() => setAsking(true)} dataEl="ADMIN-RETENTION-DEFAULTS-BTN">
            Use the platform defaults
          </Button>
        </div>
      </section>

      <Disclose open={open} onToggle={() => setOpen((now) => !now)} title="Review or change" hint="Set the days and what happens at the end for each kind of data." aside={<span>{open ? 'Close' : 'Open'}</span>}>
        <form className={styles.stack} onSubmit={submit} noValidate aria-label="Retention rules">
          <ErrorSummary errors={errors} />
          <div className={look.inner}>
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
          <div className={styles.actions}>
            <Button variant="primary" type="submit" busy={busy} dataEl="ADMIN-RETENTION-SAVE-BTN">
              Save retention rules
            </Button>
          </div>
        </form>
      </Disclose>

      {asking ? (
        <Dialog title="Use the platform defaults?" sub="Every rule above is replaced by the platform's own." onClose={() => setAsking(false)}>
          <div className={styles.actions}>
            <Button
              variant="primary"
              busy={busy}
              onClick={() => {
                setAsking(false);
                void save({ useDefaults: true }, 'The platform defaults are in use.', 'The retention rules could not be saved. Try again.', DEFAULTS);
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
    </>
  );
}
