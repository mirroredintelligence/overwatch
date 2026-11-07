import { SignOutButton, type SignOutFn } from '@/components/session/SignOutButton';
import { staffRoleWord } from '@/lib/shell/roleWords';
import type { Crumb } from './frame';
import { RoleSwitcher } from './RoleSwitcher';
import styles from './AppFrame.module.css';

// The top bar (artboard Top.dc.html): a small line (the organisation, then an optional breadcrumb), the page
// title at 20px bold, and on the right the role chip and Sign out. The title is a paragraph, not a heading:
// the page still draws its own h1 until it moves onto the frame. The chip is the role switcher (DEC-1324) when
// the person holds two or more roles, a plain label otherwise.

export type TopBarProps = {
  title: string;
  organisation?: string | null;
  breadcrumb?: readonly Crumb[];
  role?: string;
  roles?: readonly string[];
  roleWords?: Readonly<Record<string, string>>;
  signOut?: SignOutFn;
  showSignOut: boolean;
};

export function TopBar({ title, organisation, breadcrumb, role, roles, roleWords, signOut, showSignOut }: TopBarProps) {
  const switchable = role !== undefined && roles !== undefined && roles.length > 1 && roles.includes(role);
  const crumbs = breadcrumb ?? [];
  return (
    <header className={styles.top} data-noprint data-el="APP-HEADER">
      <div className={styles.heading}>
        {organisation || crumbs.length > 0 ? (
          <div className={styles.small}>
            {organisation ? <span data-el="FRAME-ORGANISATION">{organisation}</span> : null}
            {crumbs.length > 0 ? (
              <nav aria-label="Breadcrumb">
                <ol className={styles.crumbs}>
                  {crumbs.map((crumb, i) =>
                    crumb.href !== undefined && i < crumbs.length - 1 ? (
                      <li key={crumb.label}>
                        <a href={crumb.href}>{crumb.label}</a>
                        <span aria-hidden="true"> ›</span>
                      </li>
                    ) : (
                      <li key={crumb.label} aria-current={i === crumbs.length - 1 ? 'page' : undefined}>
                        {crumb.label}
                      </li>
                    ),
                  )}
                </ol>
              </nav>
            ) : null}
          </div>
        ) : null}
        {title ? <p className={styles.title}>{title}</p> : null}
      </div>
      {role !== undefined || showSignOut ? (
        <div className={styles.tools}>
          {switchable ? (
            <RoleSwitcher current={role} roles={roles} words={roleWords} />
          ) : role !== undefined ? (
            <span className={styles.roleLabel} data-el="FRAME-ROLE">
              {roleWords?.[role] ?? staffRoleWord(role)}
            </span>
          ) : null}
          {showSignOut ? <SignOutButton signOut={signOut} /> : null}
        </div>
      ) : null}
    </header>
  );
}
