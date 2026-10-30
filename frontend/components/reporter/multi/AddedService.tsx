'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { bffRequest } from '@/lib/reporter/browser';
import styles from '@/components/reporter/Reporter.module.css';

// A service the shift lead has added to this reporter (W38). The reporter says whether they look
// after it; the service goes live only after the lead's own check.

export function AddedService({ serviceId, serviceName }: { serviceId: string; serviceName: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const answer = async (accept: boolean) => {
    setBusy(true);
    const reply = await bffRequest(`/api/bff/reporter/services/${encodeURIComponent(serviceId)}/accept`, { method: 'POST', body: { accept } });
    setBusy(false);
    if (reply.status === 200 || reply.status === 204) return router.push('/app/services');
    return setNotice('We could not save your answer. Try again.');
  };

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>{`${serviceName} has been added`}</h1>
      <p>{`The SPOA shift lead added ${serviceName} to your account. Do you look after it?`}</p>
      <p>We check this with the service before it goes live. Your other services are not affected.</p>
      {notice !== null ? <Banner tone="warning" title={notice} /> : null}
      <Button variant="primary" busy={busy} dataEl="REP-ADDED-YES-BTN" onClick={() => void answer(true)}>
        {`Yes, I look after ${serviceName}`}
      </Button>
      <Button variant="neutral" busy={busy} dataEl="REP-ADDED-NO-BTN" onClick={() => void answer(false)}>
        No, this is not me
      </Button>
    </main>
  );
}
