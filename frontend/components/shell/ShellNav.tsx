'use client';

import { usePathname } from 'next/navigation';
import { isCurrent, type NavItem } from '@/lib/shell/nav';
import styles from './AppShell.module.css';

// The header's navigation: the pages of the role, the current one marked in the markup (aria-current) and by
// an underline, never by colour alone. The list is the role's; this only draws it.

export function ShellNav({ items, home }: { items: readonly NavItem[]; home: string }) {
  const pathname = usePathname() ?? '';
  if (items.length === 0) return null;
  return (
    <nav className={styles.nav} aria-label="Main">
      <ul className={styles.navList}>
        {items.map((item) => (
          <li key={item.href}>
            <a
              className={styles.navLink}
              href={item.href}
              aria-current={isCurrent(pathname, item.href, home) ? 'page' : undefined}
            >
              {item.label}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
