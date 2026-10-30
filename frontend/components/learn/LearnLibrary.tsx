'use client';

import Link from 'next/link';
import { useState, useSyncExternalStore } from 'react';
import { LEARN_ROLE_LABELS, LEARN_ROLES, lessonsFor, type LearnRole } from '@/lib/learn/content';
import { doneSnapshot, subscribeProgress } from '@/lib/learn/progress';
import styles from '../console/Console.module.css';

// The 2-minute lessons library (W53): role tabs, each lesson with its state, and the way to the
// first lesson not yet done.

export function LearnLibrary({ initialRole = 'reporter' }: { initialRole?: LearnRole }) {
  const [role, setRole] = useState<LearnRole>(initialRole);
  // The snapshot is a string, so it changes only when a lesson is marked done.
  const snapshot = useSyncExternalStore(subscribeProgress, doneSnapshot, () => '');
  const done = new Set(snapshot === '' ? [] : snapshot.split(','));
  const lessons = lessonsFor(role);
  const next = lessons.find((lesson) => !done.has(lesson.id)) ?? null;

  return (
    <main className={styles.page}>
      <h1 className={styles.heading}>2-minute lessons</h1>
      <div role="tablist" aria-label="Lesson roles" className={styles.chips}>
        {LEARN_ROLES.map((item) => (
          <button
            key={item}
            type="button"
            role="tab"
            aria-selected={role === item}
            data-el={`LEARN-TAB-${item.toUpperCase()}`}
            className={styles.tab}
            onClick={() => setRole(item)}
          >
            {LEARN_ROLE_LABELS[item]}
          </button>
        ))}
      </div>
      <ul aria-label={`${LEARN_ROLE_LABELS[role]} lessons`} className={styles.stand}>
        {lessons.map((lesson) => (
          <li key={lesson.id}>
            <Link href={`/learn/${lesson.id}`}>
              {lesson.title}
              {lesson.draft ? <span className={styles.help}> Draft</span> : null}{' '}
              <span>{done.has(lesson.id) ? `${lesson.minutes} min · done` : `${lesson.minutes} min`}</span>
            </Link>
          </li>
        ))}
      </ul>
      {next !== null && (
        <Link href={`/learn/${next.id}`} data-el="LEARN-NEXT-BTN">Start the next lesson</Link>
      )}
    </main>
  );
}
