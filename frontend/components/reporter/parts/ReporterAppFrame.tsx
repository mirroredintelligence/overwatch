'use client';

import type { ReactNode } from 'react';
import { usePathname } from 'next/navigation';
import { NotificationsNudge } from './NotificationsNudge';
import { TabBar } from './TabBar';
import styles from './ReporterAppFrame.module.css';

// The frame of the installed app (artboards B6, B9): a dark top bar with the mark, the page, and the bottom
// TabBar. The tab bar is left out where the person is not "in" the app yet or is doing one thing: the PIN,
// the 30-day check, the lock, lost phone, sign out of every phone, the notifications page and the
// practitioner's pages. The strip about blocked notifications shows wherever the tab bar does, and on the
// notifications page itself. (The staff shell has its own AppFrame; this one is the reporter's.)

const NO_TABS = ['/app/pin', '/app/verify', '/app/locked', '/app/lost-phone', '/app/sign-out-all', '/app/notifications-off', '/app/practitioner'];

const within = (path: string, base: string): boolean => path === base || path.startsWith(`${base}/`);

export function ReporterAppFrame({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? '/app';
  const tabs = !NO_TABS.some((base) => within(pathname, base));
  const nudge = tabs || within(pathname, '/app/notifications-off');
  return (
    <div className={styles.frame} data-tabs={tabs ? 'true' : 'false'}>
      <header className={styles.bar}>
        <span className={styles.brand}>
          <svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true" focusable="false">
            <circle cx="13" cy="13" r="10" fill="none" stroke="currentColor" strokeWidth="2.4" />
            <circle cx="13" cy="13" r="4.2" fill="currentColor" />
            <path d="M3 13h20" stroke="currentColor" strokeWidth="2.4" />
          </svg>
          Overwatch
        </span>
      </header>
      <div className={styles.page}>
        {nudge ? <NotificationsNudge /> : null}
        {children}
      </div>
      {tabs ? <TabBar pathname={pathname} /> : null}
    </div>
  );
}
