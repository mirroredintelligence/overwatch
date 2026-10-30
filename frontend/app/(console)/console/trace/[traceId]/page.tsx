import type { Metadata } from 'next';
import { Waterfall } from '@/components/console/Waterfall';
import styles from '@/components/console/Console.module.css';
import { getSession } from '@/lib/auth/session';
import { CONSOLE_ROLES, consoleCall, TRACE_ID_PATTERN } from '@/lib/console/backend';
import { formatMs, QUERY_BUDGET_MS, slowestSpan, type SpanView } from '@/lib/console/trace';
import { FhirError } from '@/lib/fhir/client';

export const metadata: Metadata = {
  title: 'DIUCS console: trace',
};

export const dynamic = 'force-dynamic';

type TraceResult = { name: string; totalMs: number; spans: SpanView[] };

export default async function TracePage({ params }: { params: Promise<{ traceId: string }> }) {
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

  const slowest = slowestSpan(trace.spans);
  const overBudget = slowest !== null && slowest.durationMs > QUERY_BUDGET_MS;
  const root = trace.spans.find((span) => span.parentSpanId === null);
  const outcome = root?.status === 'ok' ? 'success' : 'error';

  return (
    <main className={styles.page}>
      <h1 className={styles.heading}>Trace for {trace.name}</h1>
      <p className={styles.help}>
        Total {formatMs(trace.totalMs)} · {trace.spans.length} spans · {outcome}
      </p>
      {slowest !== null && (
        <section className={styles.section} aria-labelledby="console-slowest">
          <h2 id="console-slowest" className={styles.heading}>Slowest</h2>
          <p>
            {slowest.name}, {formatMs(slowest.durationMs)}. {overBudget ? 'Over budget. ' : ''}Budget for this query is{' '}
            {QUERY_BUDGET_MS} ms.
          </p>
        </section>
      )}
      <Waterfall totalMs={trace.totalMs} spans={trace.spans} />
    </main>
  );
}
