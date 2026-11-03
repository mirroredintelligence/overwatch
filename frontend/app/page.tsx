import { PRODUCT_NAME } from '@/lib/product';
import styles from './page.module.css';

// The same page for every host: the product's name, a one-line description and a way in, and nothing about an
// organisation. It reads nothing from the request, so it renders with no session, and some signed-in roles land here.
export default function HomePage() {
  return (
    <main className={styles.main}>
      <div className={styles.panel}>
        <div className={styles.brand}>
          <span className={styles.tile}>
            <svg width="44" height="44" viewBox="0 0 26 26" aria-hidden="true" focusable="false">
              <circle cx="13" cy="13" r="10" fill="none" stroke="#fff" strokeWidth="2.4" />
              <circle cx="13" cy="13" r="4.2" fill="#fff" />
              <path d="M3 13h20" stroke="#fff" strokeWidth="2.4" />
            </svg>
          </span>
          <h1 className={styles.product}>{PRODUCT_NAME}</h1>
        </div>
        <p className={styles.line}>The live picture of which urgent care services can take a patient right now.</p>
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
