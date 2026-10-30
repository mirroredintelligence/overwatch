'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { lessonById } from '@/lib/learn/content';
import { markDone } from '@/lib/learn/progress';
import styles from '../console/Console.module.css';

// One lesson (W53). Mark as done is kept in the progress store; the lesson shows Done on this page
// even where storage is blocked.

export function LessonView({ lessonId }: { lessonId: string }) {
  const lesson = lessonById(lessonId);
  const [done, setDone] = useState(false);
  if (lesson === undefined) return <p role="alert" className={styles.alert}>That lesson is not here.</p>;
  const current = lesson;

  function finish() {
    markDone(current.id);
    setDone(true);
  }

  return (
    <main className={styles.page}>
      <h1 className={styles.heading}>
        {lesson.title}
        {lesson.draft ? <span className={styles.help}> Draft</span> : null}
      </h1>
      {lesson.steps !== undefined ? (
        <ol>
          {lesson.steps.map((step) => (
            <li key={step.title}>
              <strong>{step.title}</strong>
              <p>{step.body}</p>
            </li>
          ))}
        </ol>
      ) : (
        <p>{lesson.placeholder}</p>
      )}
      {lesson.note !== undefined && <p>{lesson.note}</p>}
      <div className={styles.form}>
        <Button variant="secondary" href={`/learn/${lesson.id}/practice`} dataEl="LEARN-PRACTICE-BTN">
          Try it in practice mode
        </Button>
        <Button variant="primary" onClick={finish} dataEl="LEARN-DONE-BTN">
          Mark as done
        </Button>
      </div>
      {done && <p role="status">Done</p>}
    </main>
  );
}
