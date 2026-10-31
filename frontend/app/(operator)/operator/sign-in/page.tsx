import type { Metadata } from 'next';
import { Banner, Button } from '@/components/ui';
import { operatorAccessFor } from '@/lib/operator/access';
import { isSamePathOnly } from '@/lib/auth/access';
import styles from './page.module.css';

export const metadata: Metadata = {
  title: 'Platform console sign-in',
  robots: { index: false },
};

// The platform console's own sign-in (TEN-083): for the people who run the platform, from the operator's own
// directory. The page has no tenant, directory or role input and a query string cannot add one: `next` is
// carried only when it is a console page. The role comes from the back end after the sign-in.

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

const NO_ACCESS = 'Your account does not have access to the platform console.';
const FAILED = 'We could not sign you in. Try again.';

function one(value: string | string[] | undefined): string | undefined {
  return typeof value === 'string' ? value : undefined;
}

export default async function OperatorSignInPage({ searchParams }: { searchParams: SearchParams }) {
  const query = await searchParams;
  const error = one(query.error);
  const next = one(query.next);
  const message = error === 'no-access' ? NO_ACCESS : error === 'failed' ? FAILED : undefined;
  const carry = next !== undefined && isSamePathOnly(next) && operatorAccessFor(next.replace(/[?#].*$/s, '')).kind === 'guarded';
  return (
    <main className={styles.main}>
      <div className={styles.panel}>
        <h1 className={styles.product}>Platform console</h1>
        {message !== undefined ? <Banner tone="warning" title={message} dataEl="OP-SIGNIN-MESSAGE" /> : null}
        <section className={styles.card} aria-labelledby="op-signin-heading">
          <h2 id="op-signin-heading" className={styles.heading}>
            Sign in
          </h2>
          <p className={styles.text}>This is for the people who run the platform. Use your platform account.</p>
          <form className={styles.form} method="post" action="/api/bff/platform/auth/start">
            {carry ? <input type="hidden" name="next" value={next} /> : null}
            <Button variant="primary" type="submit" dataEl="OP-SIGNIN-BTN">
              Sign in with your platform account
            </Button>
          </form>
        </section>
      </div>
    </main>
  );
}
