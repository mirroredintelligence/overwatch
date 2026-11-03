'use client';

import { useEffect, useId, useState, type FormEvent } from 'react';
import { ConfirmDialog } from '@/components/blocks/ConfirmDialog';
import { Loading, Skeleton } from '@/components/ui/Skeleton';
import { CANNOT_DO, leadGet, leadPost } from '@/lib/lead/browser';
import type { ReporterPost } from '@/lib/lead/reporters';
import styles from './RemovePersonForm.module.css';

// Remove a person's access (W42). The effects are listed before the lead submits. The back end's removal
// needs the reporter's role id, which no read gives yet, so the BFF refuses the submit (DEC-651): the form is
// built and tested, and it does not send anything that could remove the wrong person.
// Submitting asks first: a confirmation (an alertdialog) names the person and the reason, and only its
// destructive button sends.

const REASONS: [string, string][] = [
  ['left-service', 'Left the service'],
  ['changed-role', 'Changed role'],
  ['lost-phone', 'Lost phone'],
  ['other', 'Other'],
];

const EFFECTS: [string, 'warn' | 'ok'][] = [
  ['The phone is signed out everywhere.', 'warn'],
  ['Notifications stop.', 'warn'],
  ['Prompts go to the cover number, or to you.', 'warn'],
  ['Past reports stay in the record.', 'ok'],
];

type LoadState = 'loading' | 'ready' | 'error';

function postsOf(value: unknown): ReporterPost[] {
  const list = (value as { reporters?: unknown } | undefined)?.reporters;
  if (!Array.isArray(list)) return [];
  return list.filter(
    (item): item is ReporterPost =>
      typeof item === 'object' && item !== null && typeof (item as ReporterPost).roleId === 'string' && typeof (item as ReporterPost).numberEnding === 'string',
  );
}

export function RemovePersonForm() {
  const [posts, setPosts] = useState<ReporterPost[]>([]);
  const [loadState, setLoadState] = useState<LoadState>('loading');
  const [attempt, setAttempt] = useState(0);
  const [person, setPerson] = useState('');
  const [reason, setReason] = useState<string | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [dialogError, setDialogError] = useState('');
  const [removed, setRemoved] = useState(false);
  const effectsId = useId();

  useEffect(() => {
    let cancelled = false;
    leadGet('/api/bff/lead/reporters')
      .then((value) => {
        if (cancelled) return;
        setPosts(postsOf(value));
        setLoadState('ready');
      })
      .catch(() => {
        if (!cancelled) setLoadState('error');
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const chosen = posts.find((post) => post.roleId === person);
  const reasonText = REASONS.find(([value]) => value === reason)?.[1];

  function retry() {
    setLoadState('loading');
    setAttempt((count) => count + 1);
  }

  function reset() {
    setPerson('');
    setReason(null);
    setErrors([]);
    setRemoved(false);
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const problems: string[] = [];
    if (chosen === undefined) problems.push('Choose who to remove');
    if (reason === null) problems.push('Choose why');
    setErrors(problems);
    setRemoved(false);
    if (problems.length > 0) return;
    setDialogError('');
    setConfirming(true);
  }

  async function remove() {
    if (busy || chosen === undefined || reason === null) return;
    setBusy(true);
    setDialogError('');
    const result = await leadPost('/api/bff/lead/people/remove', { person: chosen.roleId, reason });
    setBusy(false);
    if (result.ok) {
      setConfirming(false);
      setRemoved(true);
      return;
    }
    setDialogError(result.status === 403 ? CANNOT_DO : 'The access could not be removed. Try again.');
  }

  return (
    <main className={styles.page}>
      <div className={styles.layout}>
        <div className={styles.card}>
          <h1 className={styles.title}>{"Remove someone's access"}</h1>

          {errors.length > 0 ? (
            <div role="alert" className={styles.alert}>
              {errors.map((message) => (
                <p key={message}>{message}</p>
              ))}
            </div>
          ) : null}

          <form onSubmit={submit} noValidate className={styles.form}>
            <div className={styles.field}>
              <label htmlFor="lead-remove-person" className={styles.label}>
                Person (role or phone ending)
              </label>
              {loadState === 'loading' ? (
                <Loading label="Loading the people.">
                  <Skeleton shape="block" width="100%" />
                </Loading>
              ) : null}
              {loadState === 'error' ? (
                <div role="alert" className={styles.alert}>
                  <p>
                    <b>The people could not be loaded.</b> Try again shortly. Nothing you entered has been lost.
                  </p>
                  <div>
                    <button type="button" className={styles.quiet} onClick={retry}>
                      Try again
                    </button>
                  </div>
                </div>
              ) : null}
              {loadState === 'ready' ? (
                <select
                  id="lead-remove-person"
                  className={styles.select}
                  value={person}
                  onChange={(event) => setPerson(event.target.value)}
                >
                  <option value="">Choose who to remove</option>
                  {posts.map((post) => (
                    <option key={post.roleId} value={post.roleId}>
                      {`${post.serviceName}, ${post.role}, ending ${post.numberEnding}`}
                    </option>
                  ))}
                </select>
              ) : null}
              <p className={styles.help}>Choose the role. Its phone is shown by the last four digits.</p>
            </div>

            <fieldset className={styles.fieldset}>
              <legend className={styles.label}>Why?</legend>
              <div className={styles.options}>
                {REASONS.map(([value, text]) => (
                  <label key={value} className={styles.option}>
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
              </div>
            </fieldset>

            <div className={styles.actions}>
              <button type="submit" className={styles.danger} data-el="LEAD-REMOVE-BTN">
                Remove access
              </button>
              <button type="button" className={styles.quiet} onClick={reset}>
                Cancel
              </button>
            </div>
          </form>

          {removed ? (
            <p role="status" className={styles.notice}>
              Access removed.
            </p>
          ) : null}
        </div>

        <section className={styles.aside} aria-labelledby={effectsId}>
          <h2 id={effectsId} className={styles.asideHeading}>
            What happens
          </h2>
          <ul className={styles.ladder}>
            {EFFECTS.map(([line, tone]) => (
              <li key={line} className={styles.effect}>
                <span className={tone === 'ok' ? styles.dotOk : styles.dotWarn} aria-hidden="true" />
                {line}
              </li>
            ))}
          </ul>
          <p className={styles.asideNote}>Removing access cannot be undone from here. The person can be invited again.</p>
        </section>
      </div>

      {confirming && chosen !== undefined && reasonText !== undefined ? (
        <ConfirmDialog
          title={`Remove access for ···${chosen.numberEnding}?`}
          confirmLabel={`Remove access for ···${chosen.numberEnding}`}
          cancelLabel="Keep access"
          busy={busy}
          error={dialogError === '' ? undefined : dialogError}
          onConfirm={() => void remove()}
          onCancel={() => setConfirming(false)}
          dataEl="LEAD-REMOVE-CONFIRM"
        >
          <p className={styles.dialogText}>
            {`The ${chosen.role}'s phone will be signed out now, and prompts for ${chosen.serviceName} will come to you. Reason: ${reasonText.toLowerCase()}.`}
          </p>
        </ConfirmDialog>
      ) : null}
    </main>
  );
}
