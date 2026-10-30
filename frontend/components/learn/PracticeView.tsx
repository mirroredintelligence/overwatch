'use client';

import Link from 'next/link';
import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import styles from '../console/Console.module.css';

// Practice mode (W53). It sends nothing and makes no network request: a practice answer only changes
// what this screen says.

export function PracticeView({ lessonId }: { lessonId: string }) {
  const [answered, setAnswered] = useState(false);
  return (
    <main className={styles.page}>
      <p className={styles.help}>Sample data</p>
      <h1 className={styles.heading}>Practice</h1>
      <p className={styles.alert}>Practice. Nothing is sent.</p>
      <section className={styles.section} aria-label="Respond card">
        <p>We have 3 referrals in the next 2 hours. Still right?</p>
        {answered ? (
          <p role="status">Practice done</p>
        ) : (
          <div className={styles.form}>
            <Button variant="primary" onClick={() => setAnswered(true)} dataEl="LEARN-PRACTICE-YES-BTN">Yes, still 3</Button>
            <Button variant="secondary" onClick={() => setAnswered(true)}>Send a new number</Button>
          </div>
        )}
      </section>
      <Link href={`/learn/${lessonId}`} data-el="LEARN-LEAVE-PRACTICE-BTN">Leave practice</Link>
    </main>
  );
}
