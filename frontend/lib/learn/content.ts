// The training library (W53). The correct-a-figure lesson is the one the artboards write in full.
// The other reporter lessons have no written steps yet, so they are Draft with a placeholder body,
// and the advisor and shift-lead lessons are short Draft placeholders named from their journeys.
// No clinical or patient text is written here.

export const LEARN_ROLES = ['reporter', 'advisor', 'shift-lead'] as const;
export type LearnRole = (typeof LEARN_ROLES)[number];

export const LEARN_ROLE_LABELS: Record<LearnRole, string> = {
  reporter: 'Reporter',
  advisor: 'Advisor',
  'shift-lead': 'Shift lead',
};

export type LessonStep = { title: string; body: string };

export type Lesson = {
  id: string;
  role: LearnRole;
  title: string;
  minutes: 2;
  draft: boolean;
  steps?: readonly LessonStep[];
  note?: string;
  placeholder?: string;
};

const TO_BE_WRITTEN = 'This lesson is being written. Ask your champion for the current steps.';

export const LESSONS: readonly Lesson[] = [
  { id: 'reply-to-a-prompt', role: 'reporter', title: 'Reply to a prompt', minutes: 2, draft: true, placeholder: TO_BE_WRITTEN },
  {
    id: 'correct-a-figure',
    role: 'reporter',
    title: 'Correct a figure',
    minutes: 2,
    draft: false,
    steps: [
      { title: 'Open the notification or the app', body: 'Enter your PIN' },
      { title: 'Send the right number', body: 'The new figure replaces the old one' },
      { title: 'Check the confirmation', body: 'It shows the time recorded' },
    ],
    note: 'Corrections are fine. The board shows the latest figure and its time.',
  },
  { id: 'cover-when-away', role: 'reporter', title: 'Cover when you are away', minutes: 2, draft: true, placeholder: TO_BE_WRITTEN },
  { id: 'if-notifications-stop', role: 'reporter', title: 'If notifications stop', minutes: 2, draft: true, placeholder: TO_BE_WRITTEN },
  { id: 'start-a-call', role: 'advisor', title: 'Start a call', minutes: 2, draft: true, placeholder: TO_BE_WRITTEN },
  { id: 'request-a-booking', role: 'advisor', title: 'Request a booking', minutes: 2, draft: true, placeholder: TO_BE_WRITTEN },
  { id: 'record-the-outcome', role: 'advisor', title: 'Record the outcome', minutes: 2, draft: true, placeholder: TO_BE_WRITTEN },
  { id: 'chase-a-late-report', role: 'shift-lead', title: 'Chase a late report', minutes: 2, draft: true, placeholder: TO_BE_WRITTEN },
  { id: 'change-a-cover-number', role: 'shift-lead', title: 'Change a cover number', minutes: 2, draft: true, placeholder: TO_BE_WRITTEN },
  { id: 'review-a-registration', role: 'shift-lead', title: 'Review a registration', minutes: 2, draft: true, placeholder: TO_BE_WRITTEN },
];

export function lessonsFor(role: LearnRole): Lesson[] {
  return LESSONS.filter((lesson) => lesson.role === role);
}

export function lessonById(id: string): Lesson | undefined {
  return LESSONS.find((lesson) => lesson.id === id);
}
