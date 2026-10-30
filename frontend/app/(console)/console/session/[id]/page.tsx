import type { Metadata } from 'next';
import Link from 'next/link';
import { SessionTimeline } from '@/components/console/SessionTimeline';
import styles from '@/components/console/Console.module.css';
import { getSession } from '@/lib/auth/session';
import { CONSOLE_ROLES, consoleCall, sessionIdOf } from '@/lib/console/backend';
import { FhirError } from '@/lib/fhir/client';

export const metadata: Metadata = {
  title: 'DIUCS console: session timeline',
};

export const dynamic = 'force-dynamic';

type Events = { events: unknown[]; standout: unknown[] };

// The timeline needs a support code or an approved ticket for this session. Without one the back
// end refuses with 403, and the page says so and points back to the way in.
export default async function SessionPage({ params }: { params: Promise<{ id: string }> }) {
  const session = await getSession();
  if (!session || !CONSOLE_ROLES.includes(session.role)) {
    return (
      <main className={styles.page}>
        <p role="alert" className={styles.alert}>You do not have access to the console.</p>
      </main>
    );
  }
  const sessionId = sessionIdOf((await params).id);
  if (sessionId === null) {
    return (
      <main className={styles.page}>
        <p role="alert" className={styles.alert}>That session id is not valid.</p>
      </main>
    );
  }

  let events: Events;
  try {
    const { data } = await consoleCall<Events>(session, `/support/sessions/${encodeURIComponent(sessionId)}/events?filter=all`);
    events = data;
  } catch (error) {
    if (error instanceof FhirError && error.status === 403) {
      return (
        <main className={styles.page}>
          <section className={styles.section} aria-labelledby="console-access">
            <h1 id="console-access" className={styles.heading}>This session is not open to you</h1>
            <p className={styles.help}>
              Opening one session needs a support code the person shared, or an approved ticket. Every open is logged and
              shown to the person.
            </p>
            <Link href="/console">Find a session</Link>
          </section>
        </main>
      );
    }
    return (
      <main className={styles.page}>
        <p role="alert" className={styles.alert}>The timeline could not be loaded. Try again.</p>
      </main>
    );
  }

  return (
    <SessionTimeline sessionId={sessionId} initialEvents={events.events} initialStandout={events.standout} />
  );
}
