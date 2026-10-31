import { Logo } from '@/components/brand/Logo';
import styles from './page.module.css';

// The same page for every host: the product's logo, a way in, and nothing about an organisation. It reads
// nothing from the request, so it renders with no session, and some signed-in roles land here.
export default function HomePage() {
  return (
    <main className={styles.main}>
      <div className={styles.panel}>
        <h1 className={styles.product}>
          <Logo height={64} />
        </h1>
        <a className={styles.signIn} href="/sign-in">
          Sign in
        </a>
        <p className={styles.other}>
          <a href="/operator">Platform console</a>
        </p>
      </div>
    </main>
  );
}
