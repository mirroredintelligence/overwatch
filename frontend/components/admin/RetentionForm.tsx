'use client';

import { useState, type FormEvent } from 'react';
import { ErrorSummary, type FieldError } from '@/components/lead/ErrorSummary';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { StatusTag } from '@/components/ui/StatusTag';
import { adminSend, useAdminRead, useSubmitKey } from '@/lib/tenantAdmin/browser';
import type { Overview } from './AdminOverview';
import { Disclose } from './Disclose';
import { Loading, SkeletonRows } from '@/components/ui/Skeleton';
import styles from './admin.module.css';
import look from './Disclose.module.css';
import own from './RetentionForm.module.css';

// Data retention (TEN-076): how long each class of data is kept and what happens when the time is up. One rule
// per class, or the platform's defaults. A class with no rule is not left out: the back end stores one rule for
// each class, so a row cannot be saved while another class has none, and the message says which. The page leads
// with one answer (the defaults, custom rules, or some kinds still without one) and the schedule as chips; the
// table to change it opens on request, and one row is editable at a time.

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
const NAMES: Record<string, string> = Object.fromEntries(CLASSES);
const ACTIONS: readonly [string, string][] = [
  ['delete', 'Delete'],
  ['summarise', 'Keep a summary'],
  ['keep', 'Keep'],
];
/** Kept until the tenant is purged, so their rule is fixed and not edited here (the back end holds the same rule). */
const FIXED: readonly string[] = ['audit-chain', 'safety-concerns'];

type Rule = { days: string; action: string };
type Held = Overview['retention'];

// The platform's own schedule (DEC-271, [ASSUMED]): what "Use the platform defaults" stores. It is here only to say
// whether the rules held are those defaults; the back end is the one that stores them. A test holds this list to
// the back end's `_DEFAULT_RETENTION`.
export const DEFAULTS: Held = [
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
  const [editing, setEditing] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [asking, setAsking] = useState(false);
  const submitKey = useSubmitKey();

  function startEdit(code: string) {
    submitKey.fresh();
    setRules(toForm(held));
    setEditing(code);
    setErrors([]);
    setMessage(null);
  }

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
      setEditing(null);
      setMessage({ ok: true, text: done });
    } else setMessage({ ok: false, text: failed });
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || editing === null) return;
    const rule = rules[editing]!;
    const name = NAMES[editing]!;
    const problems: FieldError[] = [];
    if (rule.action === '') problems.push({ field: `action-${editing}`, message: `Choose what happens to ${name}.` });
    if (rule.days.trim() !== '' && !/^[1-9]\d{0,5}$/.test(rule.days.trim())) problems.push({ field: `days-${editing}`, message: 'Enter a whole number of days, 1 or more, or leave it empty.' });
    setErrors(problems);
    if (problems.length > 0) return;

    // The whole schedule goes in one save: this row's new rule, and the others as they are held.
    const wire: Held = [];
    const missing: string[] = [];
    for (const [code, label] of CLASSES) {
      if (code === editing) {
        wire.push({ dataClass: code, keepDays: rule.days.trim() === '' ? null : Number(rule.days.trim()), action: rule.action });
        continue;
      }
      const kept = held.find((r) => r.dataClass === code);
      if (kept === undefined) missing.push(label);
      else wire.push(kept);
    }
    if (missing.length > 0) {
      setErrors([{ field: `days-${editing}`, message: `Set the rules for ${missing.join(', ')} first, or use the platform defaults.` }]);
      return;
    }
    const saved = wire.find((r) => r.dataClass === editing)!;
    void save({ rules: wire }, `Saved. ${name}: ${ruleWord(saved)}.`, 'The retention rules could not be saved. Try again.', wire);
  }

  const problemOf = (field: string) => errors.find((e) => e.field === field)?.message;
  const missingAll = CLASSES.filter(([code]) => !held.some((r) => r.dataClass === code));
  const isDefaults = sameSchedule(held, DEFAULTS);
  const answer =
    missingAll.length === CLASSES.length
      ? 'No retention rules are set yet'
      : missingAll.length > 0
        ? `${CLASSES.length - missingAll.length} of ${CLASSES.length} kinds of data have a rule`
        : isDefaults
          ? 'The platform defaults are in use'
          : 'Your own rules are in use';
  const sub =
    missingAll.length > 0
      ? 'Choose a rule for each kind of data below.'
      : isDefaults
        ? 'Every kind of data has a rule. Nothing here needs you unless your information governance team wants something different.'
        : null;

  return (
    <>
    <div className={own.layout}>
      <section className={own.main} aria-label="Retention">
        <section className={own.answer} aria-label="Retention at a glance">
          <div className={own.answerHead}>
            <span className={own.answerIcon} aria-hidden="true">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                <path d="M5 12.5l4.5 4.5L19 7.5" />
              </svg>
            </span>
            <h2 className={own.answerTitle}>{answer}</h2>
          </div>
          {sub !== null ? <p className={own.answerText}>{sub}</p> : null}
          <ul className={own.chips}>
            {CLASSES.map(([code, name]) => {
              const rule = held.find((r) => r.dataClass === code);
              const cls = rule === undefined ? own.chipNotSet : rule.action === 'keep' ? own.chipKept : own.chip;
              return (
                <li key={code} className={cls}>
                  <strong>{name}:</strong> {rule === undefined ? 'not set' : ruleWord(rule)}
                </li>
              );
            })}
          </ul>
        </section>

        <Disclose open={open} onToggle={() => setOpen((now) => !now)} title="Review or change">
          <form className={styles.stack} onSubmit={submit} noValidate aria-label="Retention rules">
            <ErrorSummary errors={errors} />
            <div className={look.inner}>
              <table className={styles.table}>
                <caption className={styles.srOnly}>Retention rules</caption>
                <thead>
                  <tr>
                    <th scope="col">Kind of data</th>
                    <th scope="col">Keep for</th>
                    <th scope="col">Then</th>
                    <th scope="col">
                      <span className={styles.srOnly}>Change</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {CLASSES.map(([code, name]) => {
                    const rule = held.find((r) => r.dataClass === code);
                    if (code === editing) {
                      return (
                        <tr key={code} className={own.editing}>
                          <th scope="row">{name}</th>
                          <td>
                            <div className={own.days}>
                              <input
                                id={`days-${code}`}
                                className={own.input}
                                type="number"
                                inputMode="numeric"
                                min={1}
                                aria-label={`Days to keep ${name}`}
                                aria-invalid={problemOf(`days-${code}`) ? 'true' : undefined}
                                value={rules[code]!.days}
                                onChange={(event) => edit(code, { days: event.target.value })}
                              />
                              <span aria-hidden="true">days</span>
                            </div>
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
                          <td>
                            <Button variant="primary" type="submit" busy={busy} ariaLabel={`Save ${name}`} dataEl="ADMIN-RETENTION-SAVE-BTN">
                              Save
                            </Button>
                          </td>
                        </tr>
                      );
                    }
                    const fixed = FIXED.includes(code);
                    return (
                      <tr key={code}>
                        <th scope="row">{name}</th>
                        <td>
                          {rule === undefined ? <StatusTag variant="todo">Not set</StatusTag> : fixed ? 'Kept' : `${rule.keepDays} days`}
                        </td>
                        <td>{rule === undefined ? null : fixed ? 'No time limit' : rule.action === 'summarise' ? 'Summarised' : 'Deleted'}</td>
                        <td>
                          {fixed ? (
                            <span className={own.fixed}>Fixed</span>
                          ) : (
                            <button type="button" className={own.edit} aria-label={`Edit ${name}`} disabled={busy} onClick={() => startEdit(code)}>
                              Edit
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </form>
        </Disclose>

        {message !== null && !message.ok ? (
          <p role="alert" className={styles.problem}>
            {message.text}
          </p>
        ) : null}

        <div className={own.footer}>
          <p className={own.footerNote}>Changing a rule applies to data from now on. Nothing already deleted comes back.</p>
          <Button variant="secondary" onClick={() => setAsking(true)} dataEl="ADMIN-RETENTION-DEFAULTS-BTN">
            Use the platform defaults
          </Button>
        </div>
      </section>

      <aside aria-label="Before you change" className={own.side}>
        {isDefaults ? (
          <div className={own.warn}>
            <StatusTag variant="waiting">Check before go-live</StatusTag>
            <p className={own.text}>These defaults are the platform&apos;s proposal. Your information governance team should confirm them, especially the 7 years for case audit.</p>
          </div>
        ) : null}
        <div className={own.card}>
          <h2 className={own.cardLabel}>What each choice does</h2>
          <p className={own.text}>
            <strong>Deleted</strong>: gone after the time.
          </p>
          <p className={own.text}>
            <strong>Summarised</strong>: counts are kept, the detail goes.
          </p>
          <p className={own.text}>
            <strong>Kept</strong>: stays until your organisation leaves.
          </p>
        </div>
        {message !== null && message.ok ? (
          <div role="status" className={own.saved}>
            <span aria-hidden="true" className={own.dot}>
              ●
            </span>
            <span className={own.text}>{message.text}</span>
          </div>
        ) : null}
      </aside>
    </div>

      {asking ? (
        <Dialog title="Use the platform defaults?" sub="Every rule above is replaced by the platform's own." onClose={() => setAsking(false)}>
          <div className={styles.actions}>
            <Button
              variant="primary"
              busy={busy}
              onClick={() => {
                setAsking(false);
                void save({ useDefaults: true }, 'Saved. The platform defaults are in use.', 'The retention rules could not be saved. Try again.', DEFAULTS);
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
