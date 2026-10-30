'use client';

import { useId, useState, type FormEvent } from 'react';
import { Button } from '@/components/ui/Button';
import { CANNOT_DO, leadPost } from '@/lib/lead/browser';
import styles from './Lead.module.css';

// Remove a person's access (W42). The effects are listed before the lead submits. The back end's removal
// needs the reporter's role id, which no read gives yet, so the BFF refuses the submit (DEC-651): the form is
// built and tested, and it does not send anything that could remove the wrong person.

const REASONS: [string, string][] = [
  ['left-service', 'Left the service'],
  ['changed-role', 'Changed role'],
  ['lost-phone', 'Lost phone'],
  ['other', 'Other'],
];

const EFFECTS: string[] = [
  'The phone is signed out everywhere.',
  'Notifications stop.',
  'Prompts go to the cover number, or to you.',
  'Past reports stay in the record.',
];

export function RemovePersonForm() {
  const [person, setPerson] = useState('');
  const [reason, setReason] = useState<string | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [noticeIsError, setNoticeIsError] = useState(false);
  const effectsId = useId();

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const problems: string[] = [];
    if (person.trim() === '') problems.push('Choose who to remove');
    if (reason === null) problems.push('Choose why');
    setErrors(problems);
    setNotice('');
    if (problems.length > 0) return;
    setBusy(true);
    const result = await leadPost('/api/bff/lead/people/remove', { person: person.trim(), reason });
    setBusy(false);
    if (result.ok) {
      setNoticeIsError(false);
      setNotice('Access removed.');
      return;
    }
    setNoticeIsError(true);
    setNotice(result.status === 403 ? CANNOT_DO : 'The access could not be removed. Try again.');
  }

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Remove access</h1>

      {errors.length > 0 ? (
        <div role="alert" className={styles.fieldError}>
          {errors.map((message) => (
            <p key={message}>{message}</p>
          ))}
        </div>
      ) : null}

      <form onSubmit={(event) => void submit(event)} noValidate className={styles.stack}>
        <div className={styles.field}>
          <label htmlFor="lead-remove-person" className={styles.fieldLabel}>
            Person (role or phone ending)
          </label>
          <input
            id="lead-remove-person"
            className={styles.input}
            value={person}
            onChange={(event) => setPerson(event.target.value)}
            autoComplete="off"
          />
        </div>

        <fieldset className={styles.choices}>
          <legend className={styles.fieldLabel}>Why?</legend>
          {REASONS.map(([value, text]) => (
            <label key={value} className={styles.radio}>
              <input
                type="radio"
                name="remove-reason"
                value={value}
                checked={reason === value}
                onChange={() => setReason(value)}
                data-el={`LEAD-REMOVE-REASON-${value.toUpperCase()}`}
              />
              {text}
            </label>
          ))}
        </fieldset>

        <section className={styles.section} aria-labelledby={effectsId}>
          <h2 id={effectsId} className={styles.sectionHeading}>
            What happens
          </h2>
          <ul className={styles.ladder}>
            {EFFECTS.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </section>

        <div className={styles.actions}>
          <Button variant="primary" type="submit" busy={busy} dataEl="LEAD-REMOVE-BTN">
            Remove access
          </Button>
        </div>
      </form>

      <p role="status" className={noticeIsError ? styles.muted : styles.line}>
        {notice}
      </p>
      {noticeIsError && notice !== '' ? (
        <p role="alert" className={styles.fieldError}>
          {notice}
        </p>
      ) : null}
    </main>
  );
}
