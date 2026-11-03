'use client';

import { useId, useState, type ReactNode } from 'react';
import { Loading, Skeleton } from '@/components/ui/Skeleton';
import { bffPost } from '@/lib/bff/client';
import { parseOverview, scopeFormError, SCOPE_FLAGS } from '@/lib/registration/model';
import type { ScopeAnswer, ScopeAnswers, ScopeFlag } from '@/lib/registration/types';
import styles from './CheckStep.module.css';
import { useRead } from '@/lib/bff/useRead';

// Check 2 of 4: is it in scope? (W29, ui-screens ApprovalWeb2 screen 5; board Rev1). Four answers, a decision, and
// a reason when the decision is not the pilot. Nothing is sent until every check here passes. The pathway's name
// is tenant configuration, sent with the overview. The check is a card in the stage area: a level 2 heading.

const ANSWERS: ReadonlyArray<{ key: keyof ScopeAnswers; question: (pathway: string) => string }> = [
  { key: 'pathway', question: (pathway) => `Is the service part of the ${pathway} pathway?` },
  { key: 'spoaReferrals', question: () => 'Does it take referrals from the coordination team?' },
  { key: 'canReport', question: () => 'Can it report by app, text or email?' },
  { key: 'categoryOnList', question: () => 'Is its category on the pilot list?' },
];

const ANSWER_LABELS: ReadonlyArray<{ value: ScopeAnswer; label: string }> = [
  { value: 'yes', label: 'Yes' },
  { value: 'no', label: 'No' },
  { value: 'not-sure', label: 'Not sure' },
];

const DECISION_LABELS: Record<ScopeFlag, string> = {
  'in-pilot': 'In scope: pilot',
  later: 'In scope: later',
  'out-of-scope': 'Out of scope',
};

const TITLE = 'Is it in scope?';

function Card({ headingId, eyebrow, children }: { headingId: string; eyebrow: string; children: ReactNode }) {
  return (
    <section className={`${styles.card} ${styles.tight}`} aria-labelledby={headingId}>
      <div>
        <p className={styles.eyebrow}>{eyebrow}</p>
        <h2 id={headingId} className={styles.title}>
          {TITLE}
        </h2>
      </div>
      {children}
    </section>
  );
}

function Chip({ selected, onSelect, dataEl, children }: { selected: boolean; onSelect: () => void; dataEl: string; children: ReactNode }) {
  return (
    <button type="button" className={styles.chip} aria-pressed={selected} onClick={onSelect} data-el={dataEl}>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false" className={styles.mark}>
        <circle cx="12" cy="12" r="9" />
        {selected ? <path d="M8 12.5l2.5 2.5L16 9.5" /> : null}
      </svg>
      {children}
    </button>
  );
}

export function ScopeCheck({ id }: { id: string }) {
  const read = useRead(`/api/bff/registrations/${encodeURIComponent(id)}`, parseOverview);
  const uid = useId();
  const headingId = `${uid}-title`;
  const [answers, setAnswers] = useState<Partial<ScopeAnswers>>({});
  const [decision, setDecision] = useState<ScopeFlag | null>(null);
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  if (read.status === 'failed') {
    return (
      <Card headingId={headingId} eyebrow="Check 2 of 4">
        <p role="alert" className={styles.error}>
          <span aria-hidden="true">▲ </span>This check could not be loaded. Try again shortly.
        </p>
      </Card>
    );
  }
  if (read.status === 'loading') {
    return (
      <Card headingId={headingId} eyebrow="Check 2 of 4">
        <Loading label="Loading the scope check.">
          <Skeleton shape="block" />
          <Skeleton shape="line" width="70%" />
        </Loading>
      </Card>
    );
  }
  const pathway = read.data.pathwayName ?? 'urgent care';
  const overviewHref = `/lead/registrations/${encodeURIComponent(id)}`;

  const save = async () => {
    const found = scopeFormError(answers, decision, reason);
    setError(found);
    if (found !== null || decision === null) return;
    const { pathway: a, spoaReferrals, canReport, categoryOnList } = answers;
    if (a === undefined || spoaReferrals === undefined || canReport === undefined || categoryOnList === undefined) return;
    setBusy(true);
    setFailure(null);
    setSaved(false);
    const trimmed = reason.trim();
    const result = await bffPost(`/api/bff/registrations/${encodeURIComponent(id)}/scope`, {
      answers: { pathway: a, spoaReferrals, canReport, categoryOnList },
      decision,
      ...(trimmed !== '' ? { reason: trimmed } : {}),
    });
    setBusy(false);
    if (result.ok) setSaved(true);
    else setFailure('The decision could not be saved. Try again.');
  };

  return (
    <Card headingId={headingId} eyebrow={`Check 2 of 4 · ${read.data.serviceName}`}>
      <div className={styles.questions}>
        {ANSWERS.map((item) => {
          const questionId = `${uid}-${item.key}`;
          return (
            <div key={item.key} role="group" aria-labelledby={questionId} className={styles.question}>
              <span id={questionId} className={styles.questionText}>
                {item.question(pathway)}
              </span>
              <div className={styles.row}>
                {ANSWER_LABELS.map((option) => (
                  <Chip
                    key={option.value}
                    selected={answers[item.key] === option.value}
                    onSelect={() => setAnswers((current) => ({ ...current, [item.key]: option.value }))}
                    dataEl={`LEAD-REG-SCOPE-ANSWER-${item.key.toUpperCase()}-${option.value.toUpperCase()}`}
                  >
                    {option.label}
                  </Chip>
                ))}
              </div>
            </div>
          );
        })}
      </div>

      <div role="group" aria-labelledby={`${uid}-decision`} className={styles.group}>
        <span id={`${uid}-decision`} className={styles.label}>
          Your decision
        </span>
        <div className={styles.row}>
          {SCOPE_FLAGS.map((option) => (
            <Chip key={option} selected={decision === option} onSelect={() => setDecision(option)} dataEl={`LEAD-REG-SCOPE-DECISION-${option.toUpperCase()}`}>
              {DECISION_LABELS[option]}
            </Chip>
          ))}
        </div>
      </div>

      <p className={styles.hint}>A reason is needed only if the decision is not the pilot.</p>

      <div className={styles.field}>
        <label htmlFor={`scope-reason-${id}`} className={styles.label}>
          Reason (needed if not the pilot)
        </label>
        <p className={styles.hint}>No patient information.</p>
        <textarea
          id={`scope-reason-${id}`}
          className={styles.textarea}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          aria-invalid={error === 'Enter a reason'}
        />
        {error !== null ? (
          <p role="alert" className={styles.error}>
            <span aria-hidden="true">▲ </span>
            {error}
          </p>
        ) : null}
      </div>

      {failure !== null ? (
        <p role="alert" className={styles.error}>
          <span aria-hidden="true">▲ </span>
          {failure}
        </p>
      ) : null}
      {saved ? (
        <p aria-live="polite" className={styles.saved}>
          <span>
            <span aria-hidden="true">✓ </span>Scope decision saved.
          </span>
          <a className={styles.next} href={overviewHref}>
            Back to the review
          </a>
        </p>
      ) : null}

      <div className={styles.actions}>
        <button
          type="button"
          className={styles.primary}
          disabled={busy}
          aria-busy={busy ? 'true' : undefined}
          onClick={save}
          data-el="LEAD-REG-SCOPE-SAVE-BTN"
        >
          Save
        </button>
        <a className={styles.text} href={overviewHref}>
          Back
        </a>
      </div>
    </Card>
  );
}
