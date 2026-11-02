'use client';

import type { ReactNode } from 'react';
import { usePathname } from 'next/navigation';
import type { SignOutFn } from '@/components/session/SignOutButton';
import { itemIsCurrent, type Crumb, type FrameItem, type FramePortal } from './frame';
import { Rail } from './Rail';
import { TopBar } from './TopBar';
import styles from './AppFrame.module.css';

// The frame of every signed-in page (DEC-1326; design canvas boards admin/Rail, Top and A1): a dark rail on the
// left (a bottom bar below 900px), a white top bar over the page, and the page on the ground colour. The page
// keeps its own <main>; the frame adds none. Items are plain data (see ./frame) so a server component can
// build them. The role chip is the role switcher with two or more roles (DEC-1324) and a label otherwise.

export type { Crumb, FrameItem, FramePortal } from './frame';

export type AppFrameProps = {
  portal: FramePortal;
  items: readonly FrameItem[];
  /** The page title in the top bar. Left out, it is the label of the current item; '' shows none. */
  title?: string;
  /** The small line above the title. */
  organisation?: string | null;
  breadcrumb?: readonly Crumb[];
  /** The signed-in role (a key) and every role the person may switch to. */
  role?: string;
  roles?: readonly string[];
  /** Words for roles where they are not the default staff words. */
  roleWords?: Readonly<Record<string, string>>;
  signOut?: SignOutFn;
  /** False where nobody is signed in: no Sign out. */
  showSignOut?: boolean;
  /** The accessible name of the rail's navigation. */
  navLabel?: string;
  /** Where the mark goes. */
  homeHref?: string;
  children: ReactNode;
};

export function AppFrame({
  portal,
  items,
  title,
  organisation,
  breadcrumb,
  role,
  roles,
  roleWords,
  signOut,
  showSignOut = true,
  navLabel = 'Main',
  homeHref,
  children,
}: AppFrameProps) {
  const pathname = usePathname() ?? '';
  const heading = title ?? items.find((item) => itemIsCurrent(pathname, item))?.label ?? '';
  return (
    <div className={styles.frame} data-portal={portal} data-el="APP-SHELL">
      <Rail items={items} navLabel={navLabel} homeHref={homeHref ?? items[0]?.href ?? '/'} />
      <div className={styles.column}>
        <TopBar
          title={heading}
          organisation={organisation}
          breadcrumb={breadcrumb}
          role={role}
          roles={roles}
          roleWords={roleWords}
          signOut={signOut}
          showSignOut={showSignOut}
        />
        <div className={styles.body}>{children}</div>
      </div>
    </div>
  );
}
