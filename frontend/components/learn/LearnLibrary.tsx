'use client';

import Link from 'next/link';
import { useRef, useState, useSyncExternalStore, type KeyboardEvent, type ReactNode } from 'react';
import { LEARN_ROLE_LABELS, LEARN_ROLES, LESSONS, lessonsFor, type LearnRole } from '@/lib/learn/content';
import { doneSnapshot, subscribeProgress } from '@/lib/learn/progress';
import layout from './Learn.module.css';

// The 2-minute lessons library (W53, boards P5 and Ph3): role tabs, each lesson with its state, the open
// lesson beside the list, and the way to the first lesson not yet done. On a phone the list and the open
// lesson take turns (CSS), under a bar with Back and above a bar of Home, Learn and Help.

const ICON = { width: 22, height: 22, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true } as const;

/** The frame every learn page shares: the head (brand, title, Back on a phone), the page and the bottom bar. */
export function LearnFrame({
  back,
  title,
  titleIsHeading = false,
  meta,
  children,
}: {
  back: string;
  title: string;
  titleIsHeading?: boolean;
  meta?: string;
  children: ReactNode;
}) {
  return (
    <div className={layout.page}>
      <header className={layout.head}>
        <Link href="/" className={layout.brand} aria-label="Overwatch home">
          <svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true">
            <circle cx="13" cy="13" r="10" fill="none" stroke="currentColor" strokeWidth="2.4" />
            <circle cx="13" cy="13" r="4.2" fill="currentColor" />
            <path d="M3 13h20" stroke="currentColor" strokeWidth="2.4" />
          </svg>
        </Link>
        <Link href={back} className={layout.back} aria-label="Back">
          <svg {...ICON} strokeWidth={2.4}>
            <path d="M15 5l-7 7 7 7" />
          </svg>
        </Link>
        {titleIsHeading ? <h1 className={layout.title}>{title}</h1> : <p className={layout.title}>{title}</p>}
        {meta !== undefined && <span className={layout.count}>{meta}</span>}
      </header>
      {children}
      <nav aria-label="Sections" className={layout.bar}>
        <Link href="/" className={layout.barLink}>
          <svg {...ICON}>
            <path d="M4 11l8-7 8 7v9H4z" />
          </svg>
          Home
        </Link>
        <Link href="/learn" className={layout.barLink} aria-current="page">
          <svg {...ICON}>
            <path d="M3 6l9-3 9 3v13l-9 2-9-2zM12 3v18" />
          </svg>
          Learn
        </Link>
        <Link href="/help" className={layout.barLink}>
          <svg {...ICON}>
            <circle cx="12" cy="12" r="9" />
            <path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 .9-1 1.7M12 17h.01" />
          </svg>
          Help
        </Link>
      </nav>
    </div>
  );
}

export function LearnLibrary({
  initialRole = 'reporter',
  activeId,
  children,
  footer,
}: {
  initialRole?: LearnRole;
  /** The lesson that is open beside the list. */
  activeId?: string;
  /** The open lesson. */
  children?: ReactNode;
  footer?: ReactNode;
}) {
  const [role, setRole] = useState<LearnRole>(initialRole);
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);
  // The snapshot is a string, so it changes only when a lesson is marked done.
  const snapshot = useSyncExternalStore(subscribeProgress, doneSnapshot, () => '');
  const done = new Set(snapshot === '' ? [] : snapshot.split(','));
  const lessons = lessonsFor(role);
  const next = lessons.find((lesson) => !done.has(lesson.id)) ?? null;
  const open = children !== undefined && children !== null;

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const index = LEARN_ROLES.indexOf(role);
    const target =
      event.key === 'ArrowRight' ? (index + 1) % LEARN_ROLES.length
      : event.key === 'ArrowLeft' ? (index + LEARN_ROLES.length - 1) % LEARN_ROLES.length
      : event.key === 'Home' ? 0
      : event.key === 'End' ? LEARN_ROLES.length - 1
      : null;
    if (target === null) return;
    event.preventDefault();
    setRole(LEARN_ROLES[target]);
    tabs.current[target]?.focus();
  }

  return (
    <LearnFrame back={activeId !== undefined ? '/learn' : '/'} title="2-minute lessons" titleIsHeading meta={`${LESSONS.filter((lesson) => done.has(lesson.id)).length} of ${LESSONS.length} done`}>
      <main className={layout.split} data-open={open}>
        <section aria-label="Lessons" className={layout.listPane}>
          <div role="tablist" aria-label="Lesson roles" className={layout.tabs} onKeyDown={onKeyDown}>
            {LEARN_ROLES.map((item, index) => (
              <button
                key={item}
                ref={(element) => {
                  tabs.current[index] = element;
                }}
                type="button"
                role="tab"
                aria-selected={role === item}
                tabIndex={role === item ? 0 : -1}
                data-el={`LEARN-TAB-${item.toUpperCase()}`}
                className={layout.tab}
                onClick={() => setRole(item)}
              >
                {LEARN_ROLE_LABELS[item]}
              </button>
            ))}
          </div>
          <ul aria-label={`${LEARN_ROLE_LABELS[role]} lessons`} className={layout.lessons}>
            {lessons.map((lesson, index) => {
              const isDone = done.has(lesson.id);
              const isNext = next?.id === lesson.id;
              const state = isDone ? 'done' : isNext ? 'up next' : null;
              return (
                <li key={lesson.id}>
                  <Link
                    href={`/learn/${lesson.id}`}
                    className={layout.lesson}
                    data-next={isNext}
                    aria-current={lesson.id === activeId ? 'page' : undefined}
                  >
                    <span aria-hidden="true" className={`${layout.marker} ${isDone ? layout.markerDone : isNext ? layout.markerNext : layout.markerTodo}`}>
                      {isDone ? '✓' : index + 1}
                    </span>
                    <span className={layout.lessonText}>
                      <span className={layout.lessonTitle}>{lesson.title}</span>
                      <span className={layout.lessonMeta}>
                        {`${lesson.minutes} min`}
                        {state !== null && ` · ${state}`}
                        {lesson.draft && !isDone && (
                          <>
                            {' · '}
                            <span className={layout.draftWord}>Draft</span>
                          </>
                        )}
                      </span>
                    </span>
                    {isNext && <span aria-hidden="true" className={layout.open}>Open</span>}
                    <span aria-hidden="true" className={layout.chevron}>›</span>
                  </Link>
                </li>
              );
            })}
          </ul>
          {next !== null && (
            <Link href={`/learn/${next.id}`} className={`${layout.primary} ${layout.startNext}`} data-el="LEARN-NEXT-BTN">
              Start the next lesson
            </Link>
          )}
        </section>
        {open && <div className={layout.detail}>{children}</div>}
      </main>
      {footer}
    </LearnFrame>
  );
}
