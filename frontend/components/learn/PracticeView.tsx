'use client';

import Link from 'next/link';
import { useState } from 'react';
import { lessonById } from '@/lib/learn/content';
import { LearnFrame } from './LearnLibrary';
import layout from './Learn.module.css';

// Practice mode (W53, board P5 "Try it, nothing is sent"). It sends nothing and makes no network request:
// a practice answer only changes what this screen says.

export function PracticeView({ lessonId }: { lessonId: string }) {
  const [answered, setAnswered] = useState(false);
  const lesson = lessonById(lessonId);
  return (
    <LearnFrame back={`/learn/${lessonId}`} title="2-minute lessons">
      <main className={layout.practiceWrap}>
        <div className={layout.card}>
          {lesson !== undefined && <div className={layout.eyebrow}>{`${lesson.title} · ${lesson.minutes} minutes`}</div>}
          <p className={layout.sample}>Sample data</p>
          <h1 className={layout.cardTitle}>Practice</h1>
          <p className={layout.practiceBanner}>Practice. Nothing is sent.</p>
          <section className={layout.respond} aria-label="Respond card">
            <p>We have 3 referrals in the next 2 hours. Still right?</p>
            {answered ? (
              <p role="status" className={layout.status}>Practice done</p>
            ) : (
              <div className={layout.actions}>
                <button type="button" className={layout.primary} onClick={() => setAnswered(true)} data-el="LEARN-PRACTICE-YES-BTN">
                  Yes, still 3
                </button>
                <button type="button" className={layout.secondary} onClick={() => setAnswered(true)}>
                  Send a new number
                </button>
              </div>
            )}
          </section>
          <div className={layout.actions}>
            <Link href={`/learn/${lessonId}`} className={layout.secondary} data-el="LEARN-LEAVE-PRACTICE-BTN">Leave practice</Link>
          </div>
        </div>
      </main>
    </LearnFrame>
  );
}
