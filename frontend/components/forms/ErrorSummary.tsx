'use client';

import { useEffect, useRef } from 'react';
import type { FieldIssue } from '@/lib/register/types';
import styles from './forms.module.css';

// The error summary of a form (W54). Each message links to its field; the summary takes focus when
// it appears, so a screen reader hears what is wrong first. Shared by every registration step.

export type ErrorSummaryProps = { errors: FieldIssue[] };

export function ErrorSummary({ errors }: ErrorSummaryProps) {
  const region = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (errors.length > 0) region.current?.focus();
  }, [errors]);

  if (errors.length === 0) return null;
  const heading = errors.length === 1 ? 'There is a problem' : `There are ${errors.length} problems`;

  return (
    <div ref={region} role="alert" tabIndex={-1} className={styles.summary} data-el="REG-ERROR-SUMMARY">
      <h2 className={styles.summaryHeading}>{heading}</h2>
      <ul className={styles.summaryList}>
        {errors.map((error, index) => (
          <li key={`${error.field}-${index}`}>
            <a
              href={`#${error.field}`}
              onClick={(event) => {
                const target = document.getElementById(error.field);
                if (target === null) return;
                event.preventDefault();
                target.focus();
              }}
            >
              {error.message}
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}
