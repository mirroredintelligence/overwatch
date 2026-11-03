'use client';

import Link from 'next/link';
import { useState } from 'react';
import { LEARN_ROLE_LABELS, lessonById } from '@/lib/learn/content';
import { markDone } from '@/lib/learn/progress';
import layout from './Learn.module.css';

// One lesson (W53, board P5): the steps with the current one marked, Next step, and "Try it, nothing is
// sent". Mark as done is kept in the progress store, and is offered on the last step (or at once for a
// lesson with no written steps); the lesson shows Done on this page even where storage is blocked.

export function LessonView({ lessonId }: { lessonId: string }) {
  const lesson = lessonById(lessonId);
  const [step, setStep] = useState(0);
  const [done, setDone] = useState(false);
  if (lesson === undefined) return <p role="alert" className={layout.alert}>That lesson is not here.</p>;
  const current = lesson;
  const steps = lesson.steps ?? [];
  const onLastStep = steps.length === 0 || step >= steps.length - 1;

  function finish() {
    markDone(current.id);
    setDone(true);
  }

  return (
    <section aria-label={lesson.title} className={layout.card}>
      <div className={layout.cardTop}>
        <div className={layout.eyebrow}>{`${LEARN_ROLE_LABELS[lesson.role]} · ${lesson.minutes} minutes`}</div>
        {steps.length > 0 ? (
          <span className={layout.meta}>{`Step ${step + 1} of ${steps.length}`}</span>
        ) : lesson.draft ? (
          <span className={layout.meta}>Draft</span>
        ) : null}
      </div>
      <h2 className={layout.cardTitle}>{lesson.title}</h2>
      {steps.length > 0 ? (
        <>
          <div className={layout.segments} aria-hidden="true">
            {steps.map((item, index) => (
              <span key={item.title} className={`${layout.segment} ${index <= step ? layout.segmentOn : ''}`} />
            ))}
          </div>
          <ol className={layout.steps}>
            {steps.map((item, index) => (
              <li key={item.title} className={layout.step} aria-current={index === step ? 'step' : undefined}>
                <span
                  aria-hidden="true"
                  className={`${layout.stepMarker} ${index < step ? layout.markerDone : index === step ? layout.markerNext : layout.markerTodo}`}
                >
                  {index < step ? '✓' : index + 1}
                </span>
                <div>
                  <b className={layout.stepTitle}>{item.title}</b>
                  <span className={layout.stepBody}>{item.body}</span>
                </div>
              </li>
            ))}
          </ol>
        </>
      ) : (
        <p className={layout.placeholder}>{lesson.placeholder}</p>
      )}
      {lesson.note !== undefined && <p className={layout.note}>{lesson.note}</p>}
      <div className={layout.actions}>
        {onLastStep ? (
          <button type="button" className={layout.primary} onClick={finish} data-el="LEARN-DONE-BTN">
            Mark as done
          </button>
        ) : (
          <button type="button" className={layout.primary} onClick={() => setStep(step + 1)} data-el="LEARN-NEXT-STEP-BTN">
            Next step
          </button>
        )}
        <Link href={`/learn/${lesson.id}/practice`} className={layout.secondary} data-el="LEARN-PRACTICE-BTN">
          Try it, nothing is sent
        </Link>
      </div>
      {done && <p role="status" className={layout.status}>Done</p>}
    </section>
  );
}
