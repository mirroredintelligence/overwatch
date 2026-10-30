'use client';

import { useId, useState, type FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/Button';
import styles from './Lead.module.css';

// Find the replay of a case or booking reference (W47). The reference is checked for its shape before the
// page goes to it, so nothing that is not a reference becomes part of a path.

const REFERENCE = /^[A-Za-z0-9-]{1,40}$/;

export function AuditSearch() {
  const router = useRouter();
  const [value, setValue] = useState('');
  const [error, setError] = useState<string | null>(null);
  const inputId = useId();

  function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const reference = value.trim();
    if (!REFERENCE.test(reference)) {
      setError('Enter the case or booking reference');
      return;
    }
    setError(null);
    router.push(`/lead/audit/${encodeURIComponent(reference)}`);
  }

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Audit replay</h1>
      <form onSubmit={search} noValidate className={styles.stack}>
        <div className={styles.field}>
          <label htmlFor={inputId} className={styles.fieldLabel}>
            Case or booking reference
          </label>
          {error !== null ? (
            <p role="alert" className={styles.fieldError}>
              {error}
            </p>
          ) : null}
          <input
            id={inputId}
            className={styles.input}
            value={value}
            onChange={(event) => setValue(event.target.value)}
            autoComplete="off"
            aria-invalid={error !== null}
          />
        </div>
        <div className={styles.actions}>
          <Button variant="primary" type="submit" dataEl="LEAD-AUDIT-SEARCH-BTN">
            Find
          </Button>
        </div>
      </form>
    </main>
  );
}
