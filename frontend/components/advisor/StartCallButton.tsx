'use client';

import { useRouter } from 'next/navigation';
import { useRef, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { bffFetch, newIdempotencyKey } from '@/lib/advisor/browser';

// "Start a new call" (ADV-HOME-START-BTN). One press makes one case: the key is generated once per
// press, and a second press while the first is in flight does nothing. A failed start stays on the
// home page and says so; it does not navigate to a case that does not exist.

type Created = { id: string };

export function StartCallButton() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const inFlight = useRef(false);

  async function start() {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setFailed(false);
    const reply = await bffFetch<Created>('/api/bff/cases', {
      method: 'POST',
      idempotencyKey: newIdempotencyKey(),
    });
    if (reply.ok && typeof reply.body?.id === 'string' && reply.body.id.length > 0) {
      router.push(`/advisor/case/${encodeURIComponent(reply.body.id)}`);
      return;
    }
    inFlight.current = false;
    setBusy(false);
    setFailed(true);
  }

  return (
    <>
      <Button variant="primary" busy={busy} dataEl="ADV-HOME-START-BTN" onClick={start}>
        Start a new call
      </Button>
      {failed ? (
        <p role="alert">The call could not be started. Try again.</p>
      ) : null}
    </>
  );
}
