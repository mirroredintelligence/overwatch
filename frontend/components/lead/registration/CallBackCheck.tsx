'use client';

import { useState } from 'react';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { OptionButton } from '@/components/ui/OptionButton';
import { bffPost } from '@/lib/bff/client';
import { callbackFormError, parseOverview } from '@/lib/registration/model';
import type { CallBackResult } from '@/lib/registration/types';
import styles from '../lead.module.css';
import { useRead } from '@/lib/bff/useRead';

// Check 1 of 4: call the service back (W29, ui-screens ApprovalWeb1 screen 4). The number to call is
// the one from the register, and only that one. The directory's name comes from tenant configuration,
// sent by the back end with the overview; nothing here names an organisation.

const RESULTS: ReadonlyArray<{ value: CallBackResult; label: string }> = [
  { value: 'confirmed', label: 'Confirmed' },
  { value: 'not-confirmed', label: 'Not confirmed' },
  { value: 'no-answer', label: 'No answer' },
];

export function CallBackCheck({ id }: { id: string }) {
  const read = useRead(`/api/bff/registrations/${encodeURIComponent(id)}`, parseOverview);
  const [result, setResult] = useState<CallBackResult | null>(null);
  const [role, setRole] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  if (read.status === 'failed') return <main className={styles.page}><Banner tone="warning" title="This check could not be loaded. Try again shortly." /></main>;
  if (read.status === 'loading') return <main className={styles.page}><p>Loading…</p></main>;
  const overview = read.data;

  const numberToCall = overview.callBack?.numberToCall;
  const directory = overview.callBack?.directoryName;
  const sentence = `Phone the number on the NHS register${directory ? ` or the ${directory}` : ''}. Do not use the number the applicant gave.`;
  const name = overview.registeredBy.name;
  const registrantRole = overview.registeredBy.role;

  const save = async () => {
    if (result === null) {
      setError('Choose a result');
      return;
    }
    const found = callbackFormError(result, role);
    setError(found);
    if (found !== null || numberToCall === undefined) return;
    setBusy(true);
    setFailure(null);
    setSaved(false);
    const trimmed = role.trim();
    const answer = await bffPost(`/api/bff/registrations/${encodeURIComponent(id)}/callback`, {
      result,
      numberCalled: numberToCall,
      ...(trimmed !== '' ? { spokeToRole: trimmed } : {}),
    });
    setBusy(false);
    if (answer.ok) setSaved(true);
    else setFailure('The call-back could not be saved. Try again.');
  };

  return (
    <main className={styles.page}>
      <p className={styles.meta}>Check 1 of 4</p>
      <h1 className={styles.heading}>Call the service back</h1>
      <p className={styles.lede}>{sentence}</p>

      <dl className={styles.list}>
        <div>
          <dt>Number to call:</dt>
          <dd>
            <strong>{numberToCall ?? 'Not on the register'}</strong>
          </dd>
        </div>
        <div>
          <dt>Number the applicant gave:</dt>
          <dd>{overview.callBack?.numberGiven ?? 'Not given'}</dd>
        </div>
      </dl>

      <h2 className={styles.section}>What to say</h2>
      <ol className={styles.steps}>
        <li>Ask for {name}, or the person in charge</li>
        <li>Ask: is {name} a {registrantRole} at {overview.serviceName}?</li>
        <li>Ask: did they register for DIUCS capacity today?</li>
        <li>Do not talk about any patient</li>
      </ol>

      <fieldset className={styles.fieldset}>
        <legend>Result</legend>
        {RESULTS.map((option) => (
          <OptionButton
            key={option.value}
            selected={result === option.value}
            onSelect={() => setResult(option.value)}
            dataEl={`LEAD-REG-CALLBACK-RESULT-${option.value.toUpperCase()}`}
          >
            {option.label}
          </OptionButton>
        ))}
      </fieldset>

      <div className={styles.field}>
        <label htmlFor={`callback-role-${id}`}>Who you spoke to (role){result === 'confirmed' ? ' Required' : ''}</label>
        <input
          id={`callback-role-${id}`}
          className={styles.input}
          value={role}
          onChange={(e) => setRole(e.target.value)}
          aria-invalid={error === 'Enter who you spoke to'}
        />
        {error !== null ? <p role="alert" className={styles.error}>{error}</p> : null}
      </div>

      {result === 'no-answer' ? (
        <p className={styles.hint}>No answer? Try again, or ask the applicant for their line manager to confirm by email.</p>
      ) : null}

      {failure !== null ? <p role="alert" className={styles.error}>{failure}</p> : null}
      {saved ? (
        <p aria-live="polite">
          Call-back saved. <a href={`/lead/registrations/${encodeURIComponent(id)}?step=scope`}>Next: check 2 of 4</a>
        </p>
      ) : null}

      <div className={styles.actions}>
        <Button variant="primary" busy={busy} onClick={save} dataEl="LEAD-REG-CALLBACK-SAVE-BTN">
          Save result
        </Button>
        <Button variant="neutral" href={`/lead/registrations/${encodeURIComponent(id)}`}>
          Back
        </Button>
      </div>
    </main>
  );
}
