'use client';

import { usePathname } from 'next/navigation';
import styles from '../admin/admin.module.css';

// The network administration's navigation (TEN-080). The current page is marked with aria-current, and an
// underline for the eye (never colour alone).

const ITEMS: readonly [string, string][] = [
  ['Members', '/network-admin'],
  ['Grants', '/network-admin/grants'],
  ['Listings', '/network-admin/listings'],
  ['History', '/network-admin/history'],
];

function isCurrent(pathname: string, href: string): boolean {
  if (href === '/network-admin') return pathname === '/network-admin' || pathname === '/network-admin/';
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function NetworkAdminNav() {
  const pathname = usePathname() ?? '';
  return (
    <nav className={styles.nav} aria-label="Network administration">
      {ITEMS.map(([name, href]) => (
        <a key={href} className={styles.navLink} href={href} aria-current={isCurrent(pathname, href) ? 'page' : undefined}>
          {name}
        </a>
      ))}
    </nav>
  );
}
