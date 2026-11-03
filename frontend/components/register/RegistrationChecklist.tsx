import Link from 'next/link';
import { StatusTag, type StatusTagVariant } from '@/components/ui/StatusTag';
import styles from './RegistrationChecklist.module.css';

// The checklist of a registration: both the progress and the way back to a section (Reg board, "Your
// registration"). Stage 0 is the start page, 1 to 5 the sections, 6 the submitted page. Each entry says its
// state in a word beside its shape; the current section carries aria-current="step".

export type ChecklistState = 'not-started' | 'in-progress' | 'complete' | 'needs-attention' | 'submitted';

export const CHECKLIST_STEPS: readonly { label: string; slug: string }[] = [
  { label: 'Organisation', slug: 'organisation' },
  { label: 'Location', slug: 'location' },
  { label: 'Service', slug: 'service' },
  { label: 'Capacity reporting', slug: 'reporting' },
  { label: 'Review', slug: 'review' },
];

const WORDS: Record<ChecklistState, { word: string; variant: StatusTagVariant }> = {
  'not-started': { word: 'Not started', variant: 'todo' },
  'in-progress': { word: 'In progress', variant: 'waiting' },
  complete: { word: 'Complete', variant: 'done' },
  'needs-attention': { word: 'Needs attention', variant: 'problem' },
  submitted: { word: 'Submitted', variant: 'done' },
};

/** The state of a section when the page does not say: done before the stage, in progress at it, not started after. */
export function defaultState(step: number, stage: number): ChecklistState {
  if (stage >= 6) return 'submitted';
  if (step < stage) return 'complete';
  return step === stage ? 'in-progress' : 'not-started';
}

export function RegistrationChecklist({
  registrationId,
  stage,
  states,
}: {
  registrationId: string;
  stage: number;
  /** The state of a section by its number (1 to 5), where it is not the default for the stage. */
  states?: Partial<Record<number, ChecklistState>>;
}) {
  const base = `/register/${encodeURIComponent(registrationId)}`;
  return (
    <nav aria-label="Your registration" className={styles.nav}>
      <div className={styles.title} aria-hidden="true">
        Your registration
      </div>
      {CHECKLIST_STEPS.map((item, i) => {
        const step = i + 1;
        const state = states?.[step] ?? defaultState(step, stage);
        const { word, variant } = WORDS[state];
        return (
          <Link
            key={item.slug}
            href={`${base}/${item.slug}`}
            className={styles.item}
            data-state={state}
            aria-current={step === stage ? 'step' : undefined}
          >
            <span className={styles.label}>{item.label}</span>
            <StatusTag variant={variant}>{word}</StatusTag>
          </Link>
        );
      })}
      <p className={styles.note}>Drafts save as you go. Nothing is live until your shift lead approves it.</p>
    </nav>
  );
}
