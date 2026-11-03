import type { ReactNode } from 'react';
import { StatusTag, type StatusTagVariant } from '@/components/ui/StatusTag';
import styles from './status.module.css';

// The tracker of a submitted registration (W27): five steps in order, the current one marked with
// aria-current="step" and said in words. Each step also shows its state by shape: done steps a tick,
// the current step the half circle, the steps to come the dashed circle.

export const TRACKER_STEPS = ['Submitted', 'Checks', 'Approval', 'Test notification', 'Live'] as const;
export type TrackerStep = (typeof TRACKER_STEPS)[number];

function shapeOf(index: number, currentIndex: number): StatusTagVariant {
  if (index < currentIndex) return 'confirmed';
  if (index === currentIndex) return 'waiting';
  return 'todo';
}

export function StatusTracker({ current, details }: { current: TrackerStep; details: Partial<Record<TrackerStep, ReactNode>> }) {
  const currentIndex = TRACKER_STEPS.indexOf(current);
  return (
    <ol className={styles.tracker} aria-label="Registration progress">
      {TRACKER_STEPS.map((step, index) => (
        <li key={step} aria-current={step === current ? 'step' : undefined} className={step === current ? styles.trackerCurrent : styles.trackerStep}>
          <StatusTag variant={shapeOf(index, currentIndex)}>
            <span data-step-label>{step}</span>
          </StatusTag>
          {details[step] !== undefined ? <span className={styles.trackerDetail}>{details[step]}</span> : null}
        </li>
      ))}
    </ol>
  );
}
