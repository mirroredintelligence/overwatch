import Link from 'next/link';
import type { ReactNode } from 'react';
import { Logo } from '@/components/brand/Logo';
import { SignOutButton, type SignOutFn } from '@/components/session/SignOutButton';
import { RoleSwitcher } from '@/components/shell/RoleSwitcher';
import { staffRoleWord } from '@/lib/shell/roleWords';
import styles from './WorkspaceFrame.module.css';

// The workspace frame (WS-FRM): a top bar with the back link, the mark, the title and the one secondary action, then a
// body of the thread drawer (left, when shown) and the canvas, then a footer. There is no side rail and the page holds
// the only <main>. The role chip is the role switcher with two or more roles (DEC-1324) and a plain word otherwise.

export type WorkspaceFrameProps = {
  title: string;
  organisation?: string | null;
  backHref?: string;
  backLabel?: string;
  action?: { label: string; href: string };
  role?: string;
  roles?: readonly string[];
  roleWords?: Readonly<Record<string, string>>;
  signOut?: SignOutFn;
  showSignOut: boolean;
  /** The drawer, or null when hidden or absent. */
  thread: ReactNode;
  /** Shown in place of the drawer, only when there is no drawer. */
  assistantButton: ReactNode;
  footer?: string;
  /** The canvas. */
  children: ReactNode;
};

export function WorkspaceFrame({
  title,
  organisation,
  backHref,
  backLabel = 'Back',
  action,
  role,
  roles,
  roleWords,
  signOut,
  showSignOut,
  thread,
  assistantButton,
  footer,
  children,
}: WorkspaceFrameProps) {
  const drawer = thread !== null && thread !== undefined;
  return (
    <div className={styles.frame}>
      <header className={styles.top} data-noprint data-el="WS-FRAME-TOP">
        {backHref !== undefined ? (
          <Link className={styles.back} href={backHref} data-el="WS-FRAME-BACK">
            <span aria-hidden="true" className={styles.chevron}>
              ‹
            </span>
            {backLabel}
          </Link>
        ) : null}
        <Logo height={28} />
        <div className={styles.heading}>
          {organisation ? <p className={styles.small}>{organisation}</p> : null}
          <p className={styles.title}>{title}</p>
        </div>
        <div className={styles.spacer} />
        {action !== undefined ? (
          <Link className={styles.action} href={action.href} data-el="WS-FRAME-ACTION">
            {action.label}
          </Link>
        ) : null}
        {role !== undefined && roles !== undefined && roles.length > 1 && roles.includes(role) ? (
          <RoleSwitcher current={role} roles={roles} words={roleWords} />
        ) : role !== undefined ? (
          <span className={styles.roleLabel} data-el="FRAME-ROLE">
            {roleWords?.[role] ?? staffRoleWord(role)}
          </span>
        ) : null}
        {showSignOut ? <SignOutButton signOut={signOut} /> : null}
      </header>
      <div className={styles.body}>
        {drawer ? (
          <aside className={styles.thread} aria-label="Assistant" data-el="WS-THREAD">
            {thread}
          </aside>
        ) : null}
        <main className={styles.canvas} aria-label="Canvas" data-el="WS-CANVAS">
          {children}
        </main>
        {!drawer ? <div className={styles.assistantSlot}>{assistantButton}</div> : null}
      </div>
      <footer className={styles.foot} data-el="WS-FRAME-FOOT">
        {footer}
      </footer>
    </div>
  );
}
