import Link from 'next/link';
import type { ReactNode } from 'react';
import styles from './StickyAction.module.css';

export type StickyPrimary = { label: string; onClick?: () => void; href?: string; disabled?: boolean; busy?: boolean };
export type StickyLink = { label: string; onClick?: () => void; href?: string };
export type StickyActionProps = { primary: StickyPrimary; link?: StickyLink };

function Control({ item, className, disabled, busy }: { item: StickyLink; className: string; disabled?: boolean; busy?: boolean }): ReactNode {
  if (item.href && !disabled) {
    return (
      <Link href={item.href} className={className} onClick={item.onClick}>
        {item.label}
      </Link>
    );
  }
  return (
    <button type="button" className={className} onClick={item.onClick} disabled={disabled} aria-busy={busy ? true : undefined}>
      {item.label}
    </button>
  );
}

// The bottom bar: one primary action and one optional text link, over a fade, clear of the home indicator.
export function StickyAction({ primary, link }: StickyActionProps) {
  return (
    <div className={styles.bar}>
      <Control item={primary} className={styles.primary} disabled={primary.disabled} busy={primary.busy} />
      {link ? <Control item={link} className={styles.link} /> : null}
    </div>
  );
}
