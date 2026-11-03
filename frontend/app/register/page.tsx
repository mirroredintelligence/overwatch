import type { Metadata } from 'next';
import { Banner } from '@/components/ui/Banner';
import { SignInForm } from '@/components/register/SignInForm';
import styles from '@/components/register/entry.module.css';

// Self-registration: sign in with a text code (W23, artboard RP1). Public: the invitation token in
// ?invite= is the only thing that says which registration this is, and it is handed to the form, never
// shown. The form draws the page heading. ?saved=1 comes back from "Save and come back later".

export const metadata: Metadata = {
  title: 'Register your service - Overwatch',
  robots: { index: false },
};

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

const INVITE_TOKEN = /^[A-Za-z0-9_-]{16,128}$/;

function one(value: string | string[] | undefined): string | undefined {
  return typeof value === 'string' ? value : undefined;
}

export default async function RegisterPage({ searchParams }: { searchParams: SearchParams }) {
  const query = await searchParams;
  const invite = one(query.invite);
  const saved = one(query.saved) === '1';

  return (
    <main className={styles.page}>
      <div className={styles.column}>
        {saved ? (
          <Banner tone="info" title="Your draft is saved. Use your invitation link to come back." dataEl="REG-SAVED-NOTE" />
        ) : null}
        <SignInForm inviteToken={invite !== undefined && INVITE_TOKEN.test(invite) ? invite : undefined} />
      </div>
    </main>
  );
}
