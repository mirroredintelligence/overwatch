import type { Metadata } from 'next';
import { Banner, Button } from '@/components/ui';
import { TenantHeader } from '@/components/tenant/TenantHeader';
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

const NO_ACCESS = `Your account does not have access to ${PRODUCT_NAME}. Ask your shift lead to check your access.`;
const FAILED = 'We could not sign you in. Try again, or ask your shift lead to check your access.';
const CLINICAL_NOTE = 'Clinical advisors see case details, so this uses staff sign-in, not a texted code.';

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

  return (
    <main className={styles.main}>
      <div className={styles.panel}>
        <h1 className={styles.product}>{PRODUCT_NAME}</h1>
        <TenantHeader profile={profile} />
        {message !== undefined ? <Banner tone="warning" title={message} dataEl="SIGNIN-MESSAGE" /> : null}
        <section className={styles.card} aria-labelledby="signin-heading">
          <h2 id="signin-heading" className={styles.heading}>
            Sign in
          </h2>
          <p className={styles.text}>{words.intro}</p>
          {one(query.role) === 'clinical' ? (
            <p className={styles.text} data-el="SIGNIN-CLINICAL-NOTE">
              {CLINICAL_NOTE}
            </p>
          ) : null}
          <form className={styles.form} method="post" action="/api/bff/auth/entra/start">
            {next !== undefined && isSamePathOnly(next) ? <input type="hidden" name="next" value={next} /> : null}
            <Button variant="primary" type="submit" dataEl="SIGNIN-ENTRA-BTN">
              {words.button}
            </Button>
          </form>
          <p className={styles.help}>Having trouble? Ask your shift lead to check your access.</p>
        </section>
      </div>
    </main>
  );
}
