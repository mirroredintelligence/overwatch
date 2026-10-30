'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { type Answer, CapacityResponseForm, type Prompt } from '@/components/reporter/CapacityResponseForm';
import { splitUnitLabel } from '@/lib/links/model';
import { bffRequest } from '@/lib/reporter/browser';
import { clock } from '@/lib/reporter/times';
import styles from '@/components/reporter/Reporter.module.css';

// One service's capacity prompt in the app (W35). A figure out of the usual range is refused once
// and kept, and a second send with the same figure confirms it. Two confirms a day are the most the
// back end takes; after that only a number can be sent.

const CONFIRM_LIMIT_TEXT = 'You confirmed twice already. Please send the number.';
const SEND_NUMBER_TEXT = 'We cannot confirm that figure now. Please send the number.';

type Reported = { result?: string; serviceName?: string; value?: number; recordedAt?: string; nextDue?: string | null; low?: number; high?: number };

/** The back end's prompt, its instants shown as the tenant's clock time. */
function readPrompt(body: unknown): Prompt | null {
  const v = body as Partial<Record<keyof Prompt, unknown>> | undefined;
  if (typeof v?.service !== 'string' || typeof v.unitLabel !== 'string' || typeof v.low !== 'number' || typeof v.high !== 'number') return null;
  const recorded = typeof v.recordedValue === 'number' ? v.recordedValue : null;
  const time = (value: unknown) => (typeof value === 'string' ? clock(value) || null : null);
  return { service: v.service, unitLabel: v.unitLabel, recordedValue: recorded, asOf: time(v.asOf), low: v.low, high: v.high, replyBy: time(v.replyBy), nextDue: time(v.nextDue) };
}

export function RespondScreen({ serviceId }: { serviceId: string }) {
  const router = useRouter();
  const [prompt, setPrompt] = useState<Prompt | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmAllowed, setConfirmAllowed] = useState(true);
  const [flagged, setFlagged] = useState<number | null>(null);

  useEffect(() => {
    let live = true;
    void bffRequest(`/api/bff/reporter/services/${encodeURIComponent(serviceId)}/prompt`).then((reply) => {
      if (!live) return;
      if (reply.status === 401) return router.replace('/app/pin');
      const read = reply.status === 200 ? readPrompt(reply.body) : null;
      if (read === null) return setFailed(true);
      setPrompt(read);
    });
    return () => {
      live = false;
    };
  }, [serviceId, router]);

  if (failed) return <main className={styles.page}><p>We could not load this service. Try again shortly.</p></main>;
  if (prompt === null) return <main className={styles.page}><p role="status">Opening the update</p></main>;

  const send = async (answer: Answer) => {
    setBusy(true);
    setNotice(null);
    const body: Record<string, unknown> = { ...answer };
    if (answer.kind === 'number' && flagged === answer.value) body.confirmOutOfRange = true;
    // One key for this press: the BFF repeats a write once when its token was stale, with the same key.
    const reply = await bffRequest(`/api/bff/reporter/services/${encodeURIComponent(serviceId)}/report`, {
      method: 'POST',
      body,
      headers: { 'Idempotency-Key': crypto.randomUUID() },
    });
    setBusy(false);
    const result = reply.body as Reported | undefined;
    if (reply.status === 401) return router.replace('/app/pin');
    if (reply.status === 200 && result?.result === 'recorded' && typeof result.value === 'number' && typeof result.recordedAt === 'string') {
      // The address carries what was just recorded (the service, the figure and the instants), never a
      // number, a token or a patient detail; the thanks page shows the instants as clock time.
      const query = new URLSearchParams({
        service: result.serviceName ?? prompt.service,
        unit: splitUnitLabel(prompt.unitLabel).noun,
        value: String(result.value),
        at: result.recordedAt,
        next: result.nextDue ?? '',
      });
      return router.push(`/app/respond/${encodeURIComponent(serviceId)}/thanks?${query.toString()}`);
    }
    if (reply.status === 200 && result?.result === 'outOfRange' && typeof result.value === 'number') {
      setFlagged(result.value);
      const low = typeof result.low === 'number' ? result.low : prompt.low;
      const high = typeof result.high === 'number' ? result.high : prompt.high;
      return setNotice(`That is outside your usual range (${low} to ${high}). Send it again to confirm.`);
    }
    if (reply.status === 409 && result?.result === 'confirmLimit') {
      setConfirmAllowed(false);
      return setNotice(CONFIRM_LIMIT_TEXT);
    }
    if (reply.status === 409 && result?.result === 'sendNumber') {
      setConfirmAllowed(false);
      return setNotice(SEND_NUMBER_TEXT);
    }
    return setNotice('We could not record that. Try again.');
  };

  return (
    <CapacityResponseForm
      prompt={prompt}
      busy={busy}
      notice={notice}
      confirmAllowed={confirmAllowed}
      onAnswer={(answer) => void send(answer)}
    />
  );
}
