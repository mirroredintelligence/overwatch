import { SignOutButton, type SignOutFn } from '@/components/session/SignOutButton';
import styles from './admin.module.css';

// The foot of the administration and console pages: the way to sign out. No inline style: the content
// security policy allows styles by nonce only.

export function AdminFooter({ signOut }: { signOut?: SignOutFn }) {
  return (
    <footer className={styles.footer}>
      <SignOutButton signOut={signOut} />
    </footer>
  );
}
