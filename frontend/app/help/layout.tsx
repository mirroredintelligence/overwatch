import Link from 'next/link';
import type { ReactNode } from 'react';
import { StaffShell } from '@/app/StaffShell';
import styles from '@/components/help/Help.module.css';

// The staff header and page frame around every page of this area (components/shell), and the hub column
// beside the open page: the three ways in (boards P4 and Ph2). On a phone the hub is the /help page and the
// forms and the support code are full screen without it (Help.module.css, by the page's data-help-* mark).

const WAYS: readonly { href: string; title: string; hint: string; dataEl: string; primary?: true }[] = [
  { href: '/help/safety', title: 'Report a safety concern', hint: 'Goes to the clinical safety officer', dataEl: 'HELP-SAFETY-BTN', primary: true },
  { href: '/help/problem', title: 'Something is wrong with the tool', hint: 'A page, a figure, a message', dataEl: 'HELP-PROBLEM-BTN' },
  { href: '/help/share', title: 'Share my session with support', hint: 'Makes a code you read out', dataEl: 'HELP-SHARE-BTN' },
];

export default function Layout({ children }: { children: ReactNode }) {
  return (
    <StaffShell>
      <div className={styles.grid}>
        <nav className={styles.hub} aria-label="What do you need?">
          <p className={styles.hubLabel} aria-hidden="true">What do you need?</p>
          <ul className={styles.ways}>
            {WAYS.map((way) => (
              <li key={way.href}>
                <Link href={way.href} className={`${styles.way} ${way.primary ? styles.wayPrimary : ''}`} data-el={way.dataEl}>
                  <span className={styles.wayText}>
                    <span className={styles.wayTitle}>{way.title}</span>
                    <span className={styles.wayHint}>{way.hint}</span>
                  </span>
                  <span className={styles.chevron} aria-hidden="true">›</span>
                </Link>
              </li>
            ))}
          </ul>
          <p className={styles.urgent}>Urgent and a patient is at risk? Use your usual phone process first.</p>
        </nav>
        <div className={styles.content}>{children}</div>
      </div>
    </StaffShell>
  );
}
