'use client';

import { SignOutButton, type SignOutFn } from '@/components/session/SignOutButton';
import { signOutOperator } from '@/lib/operator/browser';
import styles from '@/components/admin/admin.module.css';

// The foot of every console page: the way to sign out, with the console's own sign-out (its own session
// route and cookies), not the tenants'.

export function OperatorFooter({ signOut = signOutOperator }: { signOut?: SignOutFn }) {
  return (
    <footer className={styles.footer}>
      <SignOutButton signOut={signOut} />
    </footer>
  );
}
