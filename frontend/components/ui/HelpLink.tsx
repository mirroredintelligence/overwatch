import Link from 'next/link';
import styles from './HelpLink.module.css';

// "Help" on every screen (W46): a link to the help page, in the shared layouts.

export function HelpLink() {
  return (
    <Link href="/help" className={styles.link} data-el="HELP-LINK">
      Help
    </Link>
  );
}
