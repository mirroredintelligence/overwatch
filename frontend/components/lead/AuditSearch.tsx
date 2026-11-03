'use client';

import { useId, useState, type FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/Button';
import styles from './Audit.module.css';

// Find the replay of a case or booking reference (W47). The reference is checked for its shape before the
// page goes to it, so nothing that is not a reference becomes part of a path.

const REFERENCE = /^[A-Za-z0-9-]{1,40}$/;

export function AuditSearch() {
  const router = useRouter();
  const [value, setValue] = useState('');
  const [error, setError] = useState<string | null>(null);
  const inputId = useId();
  const hintId = useId();
  const headingId = useId();

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
    <section className={styles.card} aria-labelledby={headingId}>
      <h2 id={headingId} className={styles.kicker}>
        Find a case
      </h2>
      <form onSubmit={search} noValidate className={styles.searchForm}>
        <label htmlFor={inputId} className={styles.searchLabel}>
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
          aria-describedby={hintId}
        />
        <p id={hintId} className={styles.hint}>
          A reference looks like C-48213 or B-20977. It is on the advisor&apos;s summary and on the booking.
        </p>
        <div className={styles.searchActions}>
          <Button variant="primary" type="submit" dataEl="LEAD-AUDIT-SEARCH-BTN">
            Replay it
          </Button>
        </div>
      </form>
    </section>
  );
}
