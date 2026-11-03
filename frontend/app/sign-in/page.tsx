import type { Metadata } from 'next';
import Link from 'next/link';
import { TenantHeader } from '@/components/tenant/TenantHeader';
import { Button } from '@/components/ui';
import { isSamePathOnly } from '@/lib/auth/access';
import { copy } from '@/lib/copy';
import { PRODUCT_NAME } from '@/lib/product';
import { currentProfile } from '@/lib/tenant/profile';
import styles from './page.module.css';

export const metadata: Metadata = {
  title: 'Sign in',
  // A sign-in page is not for search engines or caches.
  robots: { index: false },
};

// The address, and what the page does with it. `role` changes the wording only: it is never sent
// anywhere, and the role of a signed-in person comes from the verified token. `next` is carried to
// the start route only when it is a path on this site. Nothing here names a tenant or a directory:
// the page has no such input, and a query string cannot add one.
type SearchParams = Promise<Record<string, string | string[] | undefined>>;

// Each message is a bold first line and a second line, as the board sets them.
const NO_ACCESS = { lead: `Your account does not have access to ${PRODUCT_NAME}.`, body: 'Ask your shift lead to check your access.' };
const FAILED = { lead: 'We could not sign you in.', body: 'Try again, or ask your shift lead to check your access.' };
const CLINICAL_NOTE = 'Clinical advisors see case details, so this uses staff sign-in, not a texted code.';
// Said on the organisation panel only: the product does not know what kind of organisation this is.
const LEDE = 'If you work for more than one organisation, this tells you which one you are in.';
const NOT_YOURS = 'Not your organisation? Use the link your organisation gave you.';

function one(value: string | string[] | undefined): string | undefined {
  return typeof value === 'string' ? value : undefined;
}

export default async function SignInPage({ searchParams }: { searchParams: SearchParams }) {
  const query = await searchParams;
  const error = one(query.error);
  const next = one(query.next);
  const message = error === 'no-access' ? NO_ACCESS : error === 'failed' ? FAILED : undefined;
  // Which organisation this is: the host's own profile, so a person who works for two always sees which.
  const profile = await currentProfile();
  const words = copy.signIn();
  // With no organisation to show, the product's name is the page's first heading.
  const brand = (
    <>
      <span className={styles.mark}>
        <svg width="30" height="30" viewBox="0 0 26 26" aria-hidden="true">
          <circle cx="13" cy="13" r="10" fill="none" stroke="#fff" strokeWidth="2.4" />
          <circle cx="13" cy="13" r="4.2" fill="#fff" />
          <path d="M3 13h20" stroke="#fff" strokeWidth="2.4" />
        </svg>
      </span>
      <span>{PRODUCT_NAME}</span>
    </>
  );

  return (
    <main className={styles.main}>
      <div className={styles.layout}>
        <div className={styles.organisation}>
          {profile === null ? <h1 className={styles.brand}>{brand}</h1> : <p className={styles.brand}>{brand}</p>}
          <div className={styles.hero}>
            <TenantHeader profile={profile} />
            {profile !== null ? <p className={styles.lede}>{LEDE}</p> : null}
          </div>
          {profile !== null ? <p className={styles.notYours}>{NOT_YOURS}</p> : null}
        </div>

        <div className={styles.content}>
          <div className={styles.column}>
            {message !== undefined ? (
              <div className={styles.alert} role="alert" data-el="SIGNIN-MESSAGE">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#7A3500" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className={styles.alertIcon}>
                  <path d="M12 3l10 18H2z" />
                  <path d="M12 10v5M12 18h.01" />
                </svg>
                <p className={styles.alertText}>
                  <b>{message.lead}</b> {message.body}
                </p>
              </div>
            ) : null}
            <section className={styles.card} aria-labelledby="signin-heading">
              <h2 id="signin-heading" className={styles.heading}>
                Sign in
              </h2>
              <p className={styles.text}>{words.intro}</p>
              <form className={styles.form} method="post" action="/api/bff/auth/entra/start">
                {next !== undefined && isSamePathOnly(next) ? <input type="hidden" name="next" value={next} /> : null}
                <Button variant="primary" type="submit" dataEl="SIGNIN-ENTRA-BTN">
                  {words.button}
                </Button>
              </form>
              {one(query.role) === 'clinical' ? (
                <p className={styles.note} data-el="SIGNIN-CLINICAL-NOTE">
                  {CLINICAL_NOTE}
                </p>
              ) : null}
              <p className={styles.help}>Having trouble? Ask your shift lead to check your access.</p>
            </section>
          </div>
          <div className={styles.helpRow}>
            <Link href="/help" className={styles.helpLink}>
              Help
            </Link>
          </div>
        </div>
      </div>
    </main>
  );
}
