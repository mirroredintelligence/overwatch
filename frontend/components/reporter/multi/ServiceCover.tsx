'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { MOBILE_ERROR, MobileNumberField } from '@/components/reporter/MobileNumberField';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { isUkMobile } from '@/lib/forms/ukMobile';
import { bffRequest } from '@/lib/reporter/browser';
import styles from '@/components/reporter/Reporter.module.css';

// Hand one service to a cover phone while away (W38). Only that service moves; the others stay.

type Until = 'tonight' | 'this-week' | 'date';
const CHOICES: { value: Until; label: string }[] = [
  { value: 'tonight', label: 'Tonight' },
  { value: 'this-week', label: 'This week' },
  { value: 'date', label: 'A date' },
];

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
    setError(null);
    setBusy(true);
    const body = until === 'date' ? { phone, until, date } : { phone, until };
    const reply = await bffRequest(`/api/bff/reporter/services/${encodeURIComponent(serviceId)}/cover`, { method: 'POST', body });
    setBusy(false);
    if (reply.status === 200 || reply.status === 201) return router.push('/app/services');
    return setNotice('We could not hand over the service. Try again.');
  };

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>{`Cover for ${serviceName}`}</h1>
      <p>{`Choose who takes ${serviceName} while you are away. Your other services stay with you.`}</p>
      <MobileNumberField label="Cover mobile number" value={phone} onChange={setPhone} error={error} required dataEl="REP-COVER-PHONE" />
      <fieldset>
        <legend>Until</legend>
        {CHOICES.map((choice) => (
          <label key={choice.value} className={styles.question}>
            <input type="radio" name="until" value={choice.value} checked={until === choice.value} onChange={() => setUntil(choice.value)} />
            {` ${choice.label}`}
          </label>
        ))}
        {until === 'date' ? (
          <input type="date" aria-label="Cover until date" value={date} onChange={(event) => setDate(event.target.value)} className={styles.input} />
        ) : null}
      </fieldset>
      <p>We text them a code to check the number. The shift lead is told.</p>
      {notice !== null ? <Banner tone="warning" title={notice} /> : null}
      <Button variant="primary" busy={busy} dataEl="REP-COVER-SUBMIT-BTN" onClick={() => void submit()}>
        {`Hand over ${serviceName}`}
      </Button>
    </main>
  );
}
