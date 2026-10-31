'use client';

import { usePathname } from 'next/navigation';
import { ADMIN_PAGES } from './AdminOverview';
import styles from './admin.module.css';

// The administration's navigation (TEN-076). The current page is marked with aria-current, and an underline
// for the eye (never colour alone).

const ITEMS: readonly [string, string][] = [['Overview', '/admin'], ...ADMIN_PAGES];

function isCurrent(pathname: string, href: string): boolean {
  if (href === '/admin') return pathname === '/admin' || pathname === '/admin/';
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function AdminNav() {
  const pathname = usePathname() ?? '';
  return (
    <nav className={styles.nav} aria-label="Administration">
      {ITEMS.map(([name, href]) => (
        <a key={href} className={styles.navLink} href={href} aria-current={isCurrent(pathname, href) ? 'page' : undefined}>
          {name}
        </a>
      ))}
    </nav>
  );
}
