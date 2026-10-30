'use client';

import type { Ref } from 'react';
import styles from './ErrorSummary.module.css';

// The summary at the top of a form that did not go through (W18; W54 uses the same props). Each
// line links to its field, and a click moves focus to that field. Focus moves to the summary itself
// when the form is submitted, through `summaryRef`.

export type FieldError = { field: string; message: string };

export type ErrorSummaryProps = {
  errors: FieldError[];
  summaryRef?: Ref<HTMLDivElement>;
};

const FOCUSABLE = 'button, input, select, textarea, a[href]';

/** The control a link names: the element itself, or the first control inside a group. */
function focusTargetFor(id: string): HTMLElement | null {
  const target = document.getElementById(id);
  if (!target) return null;
  if (target.matches(FOCUSABLE)) return target;
  return target.querySelector<HTMLElement>(FOCUSABLE);
}

export function ErrorSummary({ errors, summaryRef }: ErrorSummaryProps) {
  if (errors.length === 0) return null;
  const count = errors.length;
  const title = count === 1 ? 'There is 1 problem' : `There are ${count} problems`;
  return (
    <div ref={summaryRef} role="alert" tabIndex={-1} className={styles.summary} data-el="FORM-ERROR-SUMMARY">
      <h2 className={styles.title}>{title}</h2>
      <ul className={styles.list}>
        {errors.map((error) => (
          <li key={error.field}>
            <a
              href={`#${error.field}`}
              onClick={(event) => {
                const target = focusTargetFor(error.field);
                if (target) {
                  event.preventDefault();
                  target.focus();
                }
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
