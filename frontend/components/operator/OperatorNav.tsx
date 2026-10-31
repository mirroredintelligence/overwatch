'use client';

import { usePathname } from 'next/navigation';
import type { OperatorRole } from '@/lib/operator/session';
import { roleWord } from '@/lib/tenantAdmin/words';
import styles from '@/components/admin/admin.module.css';

// The console's navigation (TEN-083): the pages of the role, the current one marked in the markup and by an
// underline (never colour alone), and the role said in words. The page guard is the proxy's; this only draws
// what the role can use.

const ITEMS: Record<OperatorRole, readonly [string, string][]> = {
  'platform-operator': [
    ['Tenants', '/operator'],
    ['Audit chain', '/operator/audit'],
  ],
  support: [
    ['Support requests', '/operator/support'],
    ['Tenants', '/operator'],
  ],
};

function isCurrent(pathname: string, href: string): boolean {
  if (href === '/operator') return pathname === '/operator' || pathname === '/operator/' || pathname.startsWith('/operator/tenants');
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function OperatorNav({ role }: { role: OperatorRole }) {
  const pathname = usePathname() ?? '';
  return (
    <nav className={styles.nav} aria-label="Platform console">
      {ITEMS[role].map(([name, href]) => (
        <a key={href} className={styles.navLink} href={href} aria-current={isCurrent(pathname, href) ? 'page' : undefined}>
          {name}
        </a>
      ))}
      <span className={styles.muted}>{`Signed in as ${roleWord(role).toLowerCase()}`}</span>
    </nav>
  );
}
