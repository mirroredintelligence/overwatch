'use client';

import { useState } from 'react';
import { Disclose } from '@/components/admin/Disclose';
import styles from './StepHelp.module.css';

// "Why we ask": one short reason per step, beside the form on a wide screen and a disclosure under the step's
// title on a phone. The review step (5) and the start and submitted pages have none.

export const WHY_WE_ASK: Readonly<Record<number, string>> = {
  1: 'Your ODS code lets us check your organisation against the NHS register. A real person, with a work email or phone, is who the shift lead can ring back.',
  2: 'The address gives us the position on the map, so advisors see how far you are from a patient. A visiting service tells us the area it covers instead.',
  3: 'Advisors only see patients you can take. A review date makes advisors see a flag when your criteria are out of date, so nobody relies on old rules.',
  4: 'A ward or team phone is best: it stays with the post, not the person. Services that cannot report by app, text or email are outside the pilot.',
};

export function StepHelp({ step, variant = 'card' }: { step: number; variant?: 'card' | 'disclosure' }) {
  const [open, setOpen] = useState(false);
  const text = WHY_WE_ASK[step];
  if (!text) return null;
  if (variant === 'disclosure') {
    return (
      <Disclose open={open} onToggle={() => setOpen((o) => !o)} title="Why we ask">
        <p className={styles.text}>{text}</p>
      </Disclose>
    );
  }
  return (
    <div className={styles.card}>
      <div className={styles.title}>Why we ask</div>
      <p className={styles.text}>{text}</p>
    </div>
  );
}
