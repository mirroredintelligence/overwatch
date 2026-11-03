import type { Metadata } from 'next';
import { Button } from '@/components/ui/Button';
import { Waterfall } from '@/components/console/Waterfall';
import styles from '@/components/console/Console.module.css';
import { getSession } from '@/lib/auth/session';
import { CONSOLE_ROLES, consoleCall, sessionIdOf, TRACE_ID_PATTERN } from '@/lib/console/backend';
import { formatMs, type SpanView } from '@/lib/console/trace';
import { FhirError } from '@/lib/fhir/fhirError';

export const metadata: Metadata = {
  title: 'Overwatch console: trace',
};

export const dynamic = 'force-dynamic';

type TraceResult = { name: string; totalMs: number; spans: SpanView[] };

// The session the trace was opened from (`?session=`), so "Back to the session" can return to it. A
// trace opened without one has no session to return to, and the page does not offer that link.
export default async function TracePage({
  params,
  searchParams,
}: {
  params: Promise<{ traceId: string }>;
  searchParams: Promise<{ session?: string | string[] }>;
}) {
  const session = await getSession();
  if (!session || !CONSOLE_ROLES.includes(session.role)) {
    return (
      <main className={styles.page}>
        <p role="alert" className={styles.alert}>You do not have access to the console.</p>
      </main>
    );
  }
  const { traceId } = await params;
  if (!TRACE_ID_PATTERN.test(traceId)) {
    return (
      <main className={styles.page}>
        <p role="alert" className={styles.alert}>That trace id is not valid.</p>
      </main>
    );
  }

  let trace: TraceResult;
  try {
    const { data } = await consoleCall<TraceResult>(session, `/support/traces/${traceId}`);
    trace = data;
  } catch (error) {
    const message = error instanceof FhirError && error.status === 404 ? 'No trace with that id was found.' : 'The trace could not be loaded. Try again.';
    return (
      <main className={styles.page}>
        <p role="alert" className={styles.alert}>{message}</p>
      </main>
    );
  }

  const root = trace.spans.find((span) => span.parentSpanId === null);
  const outcome = root?.status === 'ok' ? 'success' : 'error';
  const rawSession = (await searchParams).session;
  const backSession = sessionIdOf(typeof rawSession === 'string' ? rawSession : '');

  return (
    <main className={styles.page}>
      <h1 className={styles.heading}>Trace for {trace.name}</h1>
      <p className={styles.help}>
        Total {formatMs(trace.totalMs)} · {trace.spans.length} spans · {outcome}
      </p>
      <Waterfall
        totalMs={trace.totalMs}
        spans={trace.spans}
        actions={
          backSession === null ? undefined : (
            <Button variant="secondary" href={`/console/session/${encodeURIComponent(backSession)}`} dataEl="CON-TR-BACK-BTN">
              Back to the session
            </Button>
          )
        }
      />
    </main>
  );
}
