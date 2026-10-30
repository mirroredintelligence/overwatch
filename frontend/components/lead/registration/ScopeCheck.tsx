'use client';

import { useState } from 'react';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { OptionButton } from '@/components/ui/OptionButton';
import { bffPost } from '@/lib/bff/client';
import { parseOverview, scopeFormError, SCOPE_FLAGS } from '@/lib/registration/model';
import type { ScopeAnswer, ScopeAnswers, ScopeFlag } from '@/lib/registration/types';
import styles from '../lead.module.css';
import { useRead } from '@/lib/bff/useRead';

// Check 2 of 4: is it in scope? (W29, ui-screens ApprovalWeb2 screen 5). Four answers, a decision, and
// a reason when the decision is not the pilot. Nothing is sent until every check here passes. The
// pathway's name is tenant configuration, sent with the overview.

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

export function ScopeCheck({ id }: { id: string }) {
  const read = useRead(`/api/bff/registrations/${encodeURIComponent(id)}`, parseOverview);
  const [answers, setAnswers] = useState<Partial<ScopeAnswers>>({});
  const [decision, setDecision] = useState<ScopeFlag | null>(null);
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  if (read.status === 'failed') return <main className={styles.page}><Banner tone="warning" title="This check could not be loaded. Try again shortly." /></main>;
  if (read.status === 'loading') return <main className={styles.page}><p>Loading…</p></main>;
  const pathway = read.data.pathwayName ?? 'urgent care';

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
    <main className={styles.page}>
      <p className={styles.meta}>Check 2 of 4</p>
      <h1 className={styles.heading}>Is it in scope?</h1>

      {ANSWERS.map((item) => (
        <fieldset key={item.key} className={styles.fieldset}>
          <legend>{item.question(pathway)}</legend>
          {ANSWER_LABELS.map((option) => (
            <OptionButton
              key={option.value}
              selected={answers[item.key] === option.value}
              onSelect={() => setAnswers((current) => ({ ...current, [item.key]: option.value }))}
              dataEl={`LEAD-REG-SCOPE-ANSWER-${item.key.toUpperCase()}-${option.value.toUpperCase()}`}
            >
              {option.label}
            </OptionButton>
          ))}
        </fieldset>
      ))}

      <fieldset className={styles.fieldset}>
        <legend>Your decision</legend>
        {SCOPE_FLAGS.map((option) => (
          <OptionButton
            key={option}
            selected={decision === option}
            onSelect={() => setDecision(option)}
            dataEl={`LEAD-REG-SCOPE-DECISION-${option.toUpperCase()}`}
          >
            {DECISION_LABELS[option]}
          </OptionButton>
        ))}
      </fieldset>

      <div className={styles.field}>
        <label htmlFor={`scope-reason-${id}`}>Reason (needed if not the pilot)</label>
        <p className={styles.hint}>No patient information.</p>
        <textarea
          id={`scope-reason-${id}`}
          className={styles.textarea}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          aria-invalid={error === 'Enter a reason'}
        />
        {error !== null ? <p role="alert" className={styles.error}>{error}</p> : null}
      </div>

      {failure !== null ? <p role="alert" className={styles.error}>{failure}</p> : null}
      {saved ? (
        <p aria-live="polite">
          Scope decision saved. <a href={`/lead/registrations/${encodeURIComponent(id)}`}>Back to the review</a>
        </p>
      ) : null}

      <div className={styles.actions}>
        <Button variant="primary" busy={busy} onClick={save} dataEl="LEAD-REG-SCOPE-SAVE-BTN">
          Save
        </Button>
        <Button variant="neutral" href={`/lead/registrations/${encodeURIComponent(id)}`}>
          Back
        </Button>
      </div>
    </main>
  );
}
