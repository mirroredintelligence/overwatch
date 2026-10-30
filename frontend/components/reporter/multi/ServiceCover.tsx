'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { CoverUntil, NEEDS_DATE, type Until, untilBody } from '@/components/reporter/CoverUntil';
import { MOBILE_ERROR, MobileNumberField } from '@/components/reporter/MobileNumberField';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { isUkMobile } from '@/lib/forms/ukMobile';
import { bffRequest } from '@/lib/reporter/browser';
import styles from '@/components/reporter/Reporter.module.css';

// Hand one service to a cover phone while away (W38). Only that service moves; the others stay.

export function ServiceCover({ serviceId, serviceName }: { serviceId: string; serviceName: string }) {
  const router = useRouter();
  const [phone, setPhone] = useState('');
  const [until, setUntil] = useState<Until>('tonight');
  const [date, setDate] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const submit = async () => {
    if (!isUkMobile(phone)) return setError(MOBILE_ERROR);
    const choice = untilBody(until, date);
    if (choice === null) return setNotice(NEEDS_DATE);
    setError(null);
    setNotice(null);
    setBusy(true);
    const reply = await bffRequest(`/api/bff/reporter/services/${encodeURIComponent(serviceId)}/cover`, { method: 'POST', body: { phone, ...choice } });
    setBusy(false);
    setPhone('');
    if (reply.status === 401) return router.replace('/app/pin');
    if (reply.status === 200) return router.push('/app/services');
    return setNotice('We could not hand over the service. Try again.');
  };

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>{`Cover for ${serviceName}`}</h1>
      <p>{`Choose who takes ${serviceName} while you are away. Your other services stay with you.`}</p>
      <MobileNumberField label="Cover mobile number" value={phone} onChange={setPhone} error={error} required dataEl="REP-COVER-PHONE" />
      <CoverUntil until={until} date={date} onUntil={setUntil} onDate={setDate} name="until" />
      <p>We text them a code to check the number. The shift lead is told.</p>
      {notice !== null ? <Banner tone="warning" title={notice} /> : null}
      <Button variant="primary" busy={busy} dataEl="REP-COVER-SUBMIT-BTN" onClick={() => void submit()}>
        {`Hand over ${serviceName}`}
      </Button>
    </main>
  );
}
