'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { type Answer, CapacityResponseForm, type Prompt } from '@/components/reporter/CapacityResponseForm';
import { bffRequest } from '@/lib/reporter/browser';
import styles from '@/components/reporter/Reporter.module.css';

// One service's capacity prompt in the app (W35). A figure out of the usual range is refused once
// and kept, and a second send with the same figure confirms it. Two confirms a day are the most the
// back end takes; after that only a number can be sent.

const CONFIRM_LIMIT_TEXT = 'You confirmed twice already. Please send the number.';

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
      if (reply.status !== 200) return setFailed(true);
      setPrompt(reply.body as Prompt);
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
    const reply = await bffRequest(`/api/bff/reporter/services/${encodeURIComponent(serviceId)}/report`, { method: 'POST', body });
    setBusy(false);
    const result = reply.body as { result?: string; value?: number; recordedAt?: string; nextDue?: string } | undefined;
    if (reply.status === 401) return router.replace('/app/pin');
    if (reply.status === 200 && result?.result === 'recorded') {
      const query = new URLSearchParams({
        service: prompt.service,
        unit: prompt.unitLabel,
        value: String(result.value ?? ''),
        at: result.recordedAt ?? '',
        next: result.nextDue ?? '',
      });
      return router.push(`/app/respond/${encodeURIComponent(serviceId)}/thanks?${query.toString()}`);
    }
    if (reply.status === 200 && result?.result === 'outOfRange') {
      setFlagged(result.value ?? null);
      return setNotice(`That is outside your usual range (${prompt.low} to ${prompt.high}). Send it again to confirm.`);
    }
    if (reply.status === 409 && (reply.body as { result?: string } | undefined)?.result === 'confirmLimit') {
      setConfirmAllowed(false);
      return setNotice(CONFIRM_LIMIT_TEXT);
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
