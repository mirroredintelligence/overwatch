'use client';

import { useId, useState, type FormEvent } from 'react';
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
import styles from './lead.module.css';

// The small form that adds a service to the scope list (W28). The reason is checked here before
// anything is sent: a flag other than the pilot needs one (scopeReasonError). Nothing is sent when a
// check fails.

type Errors = Partial<Record<'name' | 'category' | 'flag' | 'reason', string>>;

export function AddScopeForm({ onAdded, onCancel }: { onAdded: (name: string) => void; onCancel: () => void }) {
  const ids = useId();
  const [name, setName] = useState('');
  const [category, setCategory] = useState('');
  const [flag, setFlag] = useState<ScopeFlag | ''>('');
  const [reason, setReason] = useState('');
  const [errors, setErrors] = useState<Errors>({});
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  const check = (): Errors => {
    const found: Errors = {};
    if (name.trim() === '' || name.trim().length > NAME_MAX_LENGTH) found.name = 'Enter the service name';
    if (category === '') found.category = 'Choose a category';
    if (flag === '') found.flag = 'Choose a scope flag';
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
    if (result.ok) onAdded(name.trim());
    else setFailure('The service could not be added. Check the details and try again.');
  };

  return (
    <form className={styles.field} onSubmit={submit} noValidate data-el="LEAD-SCOPE-ADD-FORM">
      <h2 className={styles.section}>Add a service to the scope list</h2>
      {failure !== null ? <p role="alert" className={styles.error}>{failure}</p> : null}

      <div className={styles.field}>
        <label htmlFor={`${ids}-name`}>Service name</label>
        <input
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

      <div className={styles.field}>
        <label htmlFor={`${ids}-category`}>Category</label>
        <select
          id={`${ids}-category`}
          className={styles.select}
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          aria-invalid={errors.category !== undefined}
        >
          <option value="">Choose a category</option>
          {CATEGORY_CODES.map((code) => (
            <option key={code} value={code}>
              {categoryLabel(code)}
            </option>
          ))}
        </select>
        {errors.category !== undefined ? <p className={styles.error}>{errors.category}</p> : null}
      </div>

      <fieldset className={styles.fieldset}>
        <legend>Scope flag</legend>
        {SCOPE_FLAGS.map((option) => (
          <label key={option} className={styles.radio}>
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
        {errors.flag !== undefined ? <p className={styles.error}>{errors.flag}</p> : null}
      </fieldset>

      <div className={styles.field}>
        <label htmlFor={`${ids}-reason`}>Reason</label>
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
          Add service
        </Button>
        <Button variant="neutral" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
