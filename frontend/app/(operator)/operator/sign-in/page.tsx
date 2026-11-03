import type { Metadata } from 'next';
import { SplitHero } from '@/components/blocks/SplitHero';
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
    <main>
      <SplitHero
        title="Platform console"
        lead={
          <>
            <strong>Set up organisations and keep them running.</strong> For the people who run the platform. Every step you
            take here is recorded in a chain that cannot be changed afterwards.
          </>
        }
        footnote="Staff of an organisation sign in at their own address, not here."
        contentLabel="Sign in"
      >
        {message !== undefined ? (
          <div className={styles.notice}>
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className={styles.icon}>
              <path d="M12 3l10 18H2z" />
              <path d="M12 10v5M12 18h.01" />
            </svg>
            <Banner tone="warning" title={message} dataEl="OP-SIGNIN-MESSAGE" />
          </div>
        ) : null}
        <div className={styles.card}>
          <h2 className={styles.heading}>Sign in</h2>
          <p className={styles.text}>
            This is for the people who run the platform. Use your platform account.{' '}
            <span>There is no new password.</span>
          </p>
          <form className={styles.form} method="post" action="/api/bff/platform/auth/start">
            {carry ? <input type="hidden" name="next" value={next} /> : null}
            <Button variant="primary" type="submit" dataEl="OP-SIGNIN-BTN">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                <rect x="2" y="2" width="9.5" height="9.5" />
                <rect x="12.5" y="2" width="9.5" height="9.5" />
                <rect x="2" y="12.5" width="9.5" height="9.5" />
                <rect x="12.5" y="12.5" width="9.5" height="9.5" />
              </svg>
              Sign in with your platform account
            </Button>
          </form>
          <p className={styles.help}>Having trouble? Ask the person who runs the platform to check your access.</p>
        </div>
      </SplitHero>
    </main>
  );
}
