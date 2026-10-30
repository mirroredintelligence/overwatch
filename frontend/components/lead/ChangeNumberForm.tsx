'use client';

import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { Button } from '@/components/ui/Button';
import { Chip } from '@/components/ui/Chip';
import { isUkMobile } from '@/lib/forms/ukMobile';
import { leadGet, leadPost, newIdempotencyKey } from '@/lib/lead/browser';
import styles from './Lead.module.css';

// Change a reporter's number for leave or cover (W18, pilot). The old number stops working as soon as
// the change is saved. The full new number is never shown back: the answer carries the last four digits
// only, and the field is cleared once the change is saved (H-331).

const COVERS: [string, string][] = [
  ['today', 'Today'],
  ['this-week', 'This week'],
  ['until-changed', 'Until I change it'],
];

type Choice = { id: string; name: string };

function choicesFrom(value: unknown): Choice[] {
  const list = (value as { services?: unknown } | undefined)?.services;
  if (!Array.isArray(list)) return [];
  return list.filter(
    (item): item is Choice =>
      typeof item === 'object' &&
      item !== null &&
      typeof (item as Choice).id === 'string' &&
      typeof (item as Choice).name === 'string',
  );
}

export function ChangeNumberForm({ serviceId }: { serviceId?: string }) {
  const [services, setServices] = useState<Choice[]>([]);
  const [service, setService] = useState<string>(serviceId ?? '');
  const [mobile, setMobile] = useState('');
  const [until, setUntil] = useState<string | null>(null);
  const [mobileError, setMobileError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const keyRef = useRef<string | null>(null);
  const mobileId = useId();
  const groupId = useId();

  useEffect(() => {
    let cancelled = false;
    leadGet('/api/bff/lead/services')
      .then((value) => {
        if (!cancelled) setServices(choicesFrom(value));
      })
      .catch(() => {
        if (!cancelled) setServices([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving) return;
    setFailure(null);
    if (!isUkMobile(mobile)) {
      setMobileError('Enter a UK mobile number, like 07700 900456');
      return;
    }
    setMobileError(null);
    if (service === '' || until === null) {
      setFailure('Choose the service and how long the cover lasts.');
      return;
    }
    keyRef.current ??= newIdempotencyKey();
    setSaving(true);
    const result = await leadPost(
      '/api/bff/lead/reporters/number',
      { serviceId: service, newNumber: mobile, until },
      keyRef.current,
    );
    setSaving(false);
    if (!result.ok) {
      setFailure('The number could not be changed. Try again.');
      return;
    }
    keyRef.current = null;
    const ending = (result.body as { numberEnding?: unknown } | undefined)?.numberEnding;
    setSaved(typeof ending === 'string' ? ending : '');
    setMobile('');
  }

  async function testText() {
    if (service === '') return;
    const result = await leadPost(`/api/bff/lead/services/${encodeURIComponent(service)}/test-prompt`);
    setTesting(result.ok ? 'Test text sent.' : 'The test text could not be sent.');
  }

  return (
    <main className={styles.page}>
      <header className={styles.stack}>
        <p className={styles.muted}>Cover for leave</p>
        <h1 className={styles.title}>Change reporter number</h1>
      </header>

      <form onSubmit={(event) => void save(event)} noValidate className={styles.stack}>
        <div className={styles.field}>
          <label htmlFor="lead-num-service" className={styles.fieldLabel}>
            Service
          </label>
          <select
            id="lead-num-service"
            className={styles.input}
            value={service}
            onChange={(event) => setService(event.target.value)}
          >
            <option value="">Choose a service</option>
            {services.map((choice) => (
              <option key={choice.id} value={choice.id}>
                {choice.name}
              </option>
            ))}
          </select>
        </div>

        <div className={styles.field}>
          <label htmlFor={mobileId} className={styles.fieldLabel}>
            New mobile number
          </label>
          {mobileError ? (
            <p role="alert" className={styles.fieldError}>
              {mobileError}
            </p>
          ) : null}
          <input
            id={mobileId}
            className={styles.input}
            inputMode="tel"
            autoComplete="off"
            value={mobile}
            onChange={(event) => setMobile(event.target.value)}
          />
        </div>

        <div role="group" aria-labelledby={groupId} className={styles.choices}>
          <p id={groupId} className={styles.fieldLabel}>
            How long?
          </p>
          <div className={styles.chipRow}>
            {COVERS.map(([value, text]) => (
              <Chip
                key={value}
                pressed={until === value}
                onPressedChange={() => setUntil(value)}
                dataEl={`LEAD-NUM-UNTIL-${value.toUpperCase()}`}
              >
                {text}
              </Chip>
            ))}
          </div>
        </div>

        <p className={styles.muted}>The old number stops working as soon as you save. Both numbers are logged.</p>

        <div className={styles.actions}>
          <Button variant="secondary" disabled={saved === null} onClick={() => void testText()} dataEl="LEAD-NUM-TEST-BTN">
            Send a test text
          </Button>
          <Button variant="primary" type="submit" busy={saving} dataEl="LEAD-NUM-SAVE-BTN">
            Save
          </Button>
        </div>
      </form>

      {failure ? (
        <p role="alert" className={styles.fieldError}>
          {failure}
        </p>
      ) : null}
      <p role="status" className={styles.line}>
        {saved !== null ? `New number ending ${saved} saved` : ''}
        {testing !== null ? ` ${testing}` : ''}
      </p>
    </main>
  );
}
