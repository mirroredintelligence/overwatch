'use client';

import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { Button } from '@/components/ui/Button';
import { bffPost } from '@/lib/bff/client';
import {
  CATEGORY_CODES,
  NAME_MAX_LENGTH,
  NOTE_MAX_LENGTH,
  SCOPE_FLAGS,
  categoryLabel,
  flagLabel,
  scopeReasonError,
} from '@/lib/registration/model';
import type { ScopeFlag } from '@/lib/registration/types';
import styles from './AddScopeForm.module.css';

// The panel that adds a service to the scope list (W28). It sits beside the list as a labelled region,
// not a modal, so the list stays readable. The reason is checked here before anything is sent: a flag
// other than the pilot needs one (scopeReasonError). Nothing is sent when a check fails.

type Errors = Partial<Record<'name' | 'category' | 'flag' | 'reason', string>>;

/** What the list needs to confirm the add: the name, the flag, and the new service's id when the back end gives one. */
export type AddedScope = { name: string; flag: ScopeFlag; serviceId: string | null };

function serviceIdOf(data: unknown): string | null {
  if (typeof data === 'object' && data !== null && 'serviceId' in data && typeof data.serviceId === 'string') {
    return data.serviceId;
  }
  return null;
}

export function AddScopeForm({ onAdded, onCancel }: { onAdded: (entry: AddedScope) => void; onCancel: () => void }) {
  const ids = useId();
  const nameRef = useRef<HTMLInputElement>(null);
  const [name, setName] = useState('');
  const [category, setCategory] = useState('');
  const [flag, setFlag] = useState<ScopeFlag | ''>('');
  const [reason, setReason] = useState('');
  const [errors, setErrors] = useState<Errors>({});
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  // The panel opens because the person chose to add: the first thing they need is the name field.
  useEffect(() => {
    nameRef.current?.focus();
  }, []);

  const check = (): Errors => {
    const found: Errors = {};
    if (name.trim() === '' || name.trim().length > NAME_MAX_LENGTH) found.name = 'Enter the service name';
    if (category === '') found.category = 'Choose a category';
    if (flag === '') found.flag = 'Choose where the service stands';
    else {
      const reasonError = scopeReasonError(flag, reason);
      if (reasonError !== null) found.reason = reasonError;
    }
    return found;
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const found = check();
    setErrors(found);
    if (Object.keys(found).length > 0 || flag === '') return;
    setBusy(true);
    setFailure(null);
    const trimmed = reason.trim();
    const result = await bffPost('/api/bff/scope', {
      name: name.trim(),
      category,
      flag,
      ...(trimmed !== '' ? { reason: trimmed } : {}),
    });
    setBusy(false);
    if (result.ok) onAdded({ name: name.trim(), flag, serviceId: serviceIdOf(result.data) });
    else setFailure('The service could not be added. Check the details and try again.');
  };

  return (
    <section className={styles.panel} aria-label="Add a service to the scope list">
      <form className={styles.form} onSubmit={submit} noValidate data-el="LEAD-SCOPE-ADD-FORM">
        <p className={styles.kicker}>New entry</p>
        <h2 className={styles.title}>Add a service to the scope list</h2>
        {failure !== null ? <p role="alert" className={styles.error}>{failure}</p> : null}

        <div className={styles.field}>
          <label htmlFor={`${ids}-name`} className={styles.label}>Service name</label>
          <input
            ref={nameRef}
            id={`${ids}-name`}
            className={styles.input}
            value={name}
            maxLength={NAME_MAX_LENGTH}
            onChange={(e) => setName(e.target.value)}
            aria-invalid={errors.name !== undefined}
            aria-describedby={errors.name !== undefined ? `${ids}-name-error` : undefined}
          />
          {errors.name !== undefined ? <p id={`${ids}-name-error`} className={styles.error}>{errors.name}</p> : null}
        </div>

        <fieldset className={styles.group} aria-describedby={errors.category !== undefined ? `${ids}-category-error` : undefined}>
          <legend className={styles.label}>Category</legend>
          <div className={styles.chips}>
            {CATEGORY_CODES.map((code) => (
              <label key={code} className={styles.chip}>
                <input
                  type="radio"
                  name={`${ids}-category`}
                  value={code}
                  checked={category === code}
                  onChange={() => setCategory(code)}
                />
                {categoryLabel(code)}
              </label>
            ))}
          </div>
          {errors.category !== undefined ? <p id={`${ids}-category-error`} className={styles.error}>{errors.category}</p> : null}
        </fieldset>

        <fieldset className={styles.group}>
          <legend className={styles.label}>Where does it stand?</legend>
          <div className={styles.chips}>
            {SCOPE_FLAGS.map((option) => (
              <label key={option} className={styles.chip}>
                <input
                  type="radio"
                  name={`${ids}-flag`}
                  value={option}
                  checked={flag === option}
                  onChange={() => setFlag(option)}
                />
                {flagLabel(option)}
              </label>
            ))}
          </div>
          {errors.flag !== undefined ? <p className={styles.error}>{errors.flag}</p> : null}
        </fieldset>

        <div className={styles.field}>
          <label htmlFor={`${ids}-reason`} className={styles.label}>Reason</label>
          <p id={`${ids}-reason-hint`} className={styles.hint}>
            Needed unless the service is in the pilot. No patient information. Up to {NOTE_MAX_LENGTH} characters.
          </p>
          <textarea
            id={`${ids}-reason`}
            className={styles.textarea}
            value={reason}
            maxLength={NOTE_MAX_LENGTH}
            onChange={(e) => setReason(e.target.value)}
            aria-describedby={`${ids}-reason-hint`}
            aria-invalid={errors.reason !== undefined}
          />
          {errors.reason !== undefined ? <p className={styles.error}>{errors.reason}</p> : null}
        </div>

        <div className={styles.actions}>
          <Button type="submit" variant="primary" busy={busy} dataEl="LEAD-SCOPE-ADD-SAVE-BTN">
            Add to the list
          </Button>
          <Button variant="neutral" onClick={onCancel}>
            Cancel
          </Button>
        </div>
      </form>
    </section>
  );
}
