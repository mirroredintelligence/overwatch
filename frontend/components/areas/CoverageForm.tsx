'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { ErrorSummary, type FieldError } from '@/components/lead/ErrorSummary';
import { Button } from '@/components/ui/Button';
import { Chip } from '@/components/ui/Chip';
import { bffFetch, newIdempotencyKey } from '@/lib/advisor/browser';
import {
  type CoverageForm as Form,
  type CoverageProblem,
  DAYS,
  type DayCode,
  MAX_RESPONSE_HOURS,
  overlapWith,
  parseCoverageForm,
  problemsOf,
} from '@/lib/areas/types';
import styles from './coverage.module.css';

// Define a coverage area (RadarWeb 5): where one visiting service goes, as postcode districts, how fast it
// aims to get there, and which days it visits. Areas are districts so they match how patients are placed.
// The overlap note names any other service that already covers a chosen district; it is information, not a
// block: advisors will see both and compare them. No map: the back end holds no district outlines, so the
// districts are chips and the overlap is said in words.

const PROBLEMS: Record<CoverageProblem, { field: string; message: string }> = {
  districts: { field: 'cov-districts', message: 'Choose at least one district.' },
  hours: { field: 'cov-hours', message: `Enter the response target in whole hours, from 1 to ${MAX_RESPONSE_HOURS}.` },
  days: { field: 'cov-days', message: 'Choose at least one day you visit.' },
};

type Load = { kind: 'loading' } | { kind: 'failed'; notFound: boolean } | { kind: 'ready'; form: Form };

export function CoverageForm({ serviceId }: { serviceId: string }) {
  const id = encodeURIComponent(serviceId);
  const hoursId = useId();
  const [load, setLoad] = useState<Load>({ kind: 'loading' });
  const [districts, setDistricts] = useState<string[]>([]);
  const [hours, setHours] = useState('');
  const [days, setDays] = useState<DayCode[]>([]);
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<'saved' | 'failed' | null>(null);
  const summary = useRef<HTMLDivElement>(null);
  const requested = useRef<string | null>(null);

  const apply = (form: Form) => {
    setLoad({ kind: 'ready', form });
    setDistricts(form.districts);
    setHours(form.responseHours === null ? '' : String(form.responseHours));
    setDays(form.days);
  };

  const read = async () => {
    const reply = await bffFetch<unknown>(`/api/bff/lead/services/${id}/coverage`);
    const form = reply.ok ? parseCoverageForm(reply.body) : null;
    if (form === null) {
      setLoad({ kind: 'failed', notFound: !reply.ok && reply.status === 404 });
      return;
    }
    apply(form);
  };

  useEffect(() => {
    if (requested.current === serviceId) return;
    requested.current = serviceId;
    void read();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- one read per service
  }, [serviceId]);

  if (load.kind === 'loading') return <main className={styles.screen}><p role="status">Loading the coverage area.</p></main>;
  if (load.kind === 'failed') {
    return (
      <main className={styles.screen}>
        <p role="alert">
          {load.notFound ? 'The coverage area is not available for this service yet.' : 'The coverage area could not be read. Try again.'}
        </p>
        <div className={styles.actions}>
          <Button variant="secondary" onClick={() => { setLoad({ kind: 'loading' }); void read(); }} dataEl="COV-RETRY-BTN">
            Try again
          </Button>
          <Button variant="neutral" href="/lead">
            Back
          </Button>
        </div>
      </main>
    );
  }

  const { form } = load;
  const overlap = overlapWith(form, districts);
  const toggle = <T extends string>(list: T[], value: T, on: boolean): T[] => (on ? [...list, value].filter((v, i, all) => all.indexOf(v) === i) : list.filter((v) => v !== value));

  const save = async () => {
    if (saving) return;
    const problems = problemsOf({ districts, responseHours: hours, days });
    setMessage(null);
    if (problems.length > 0) {
      setErrors(problems.map((problem) => PROBLEMS[problem]));
      queueMicrotask(() => summary.current?.focus());
      return;
    }
    setErrors([]);
    setSaving(true);
    const reply = await bffFetch<unknown>(`/api/bff/lead/services/${id}/coverage`, {
      method: 'PUT',
      body: { districts, responseHours: Number(hours), days },
      idempotencyKey: newIdempotencyKey(),
    });
    const saved = reply.ok ? parseCoverageForm(reply.body) : null;
    if (saved === null) {
      setMessage('failed');
    } else {
      apply(saved);
      setMessage('saved');
    }
    setSaving(false);
  };

  return (
    <main className={styles.screen}>
      <h1 className={styles.heading}>{`Where does ${form.serviceName} go?`}</h1>
      <p className={styles.sub}>Areas are postcode districts or sectors, so they match how patients are placed.</p>
      <ErrorSummary errors={errors} summaryRef={summary} />

      <fieldset id="cov-districts" className={styles.chips}>
        <legend className={styles.legend}>Districts you cover (required)</legend>
        {form.available.map((district) => (
          <Chip key={district} pressed={districts.includes(district)} onPressedChange={(on) => setDistricts((list) => toggle(list, district, on))} dataEl={`COV-DISTRICT-${district}`}>
            {district}
          </Chip>
        ))}
      </fieldset>

      <div className={styles.field}>
        <label htmlFor={hoursId} className={styles.legend}>
          Response target (hours) (required)
        </label>
        <input
          id={hoursId}
          className={styles.input}
          type="text"
          inputMode="numeric"
          autoComplete="off"
          value={hours}
          onChange={(event) => setHours(event.target.value)}
          data-el="COV-HOURS"
        />
      </div>

      <fieldset id="cov-days" className={styles.chips}>
        <legend className={styles.legend}>Days you visit (required)</legend>
        {DAYS.map((day) => (
          <Chip key={day.value} pressed={days.includes(day.value)} onPressedChange={(on) => setDays((list) => toggle(list, day.value, on))} dataEl={`COV-DAY-${day.value.toUpperCase()}`}>
            {day.label}
          </Chip>
        ))}
      </fieldset>

      {overlap.length === 0 ? null : (
        <p className={styles.overlap} data-el="COV-OVERLAP">
          <strong>Overlap.</strong>{' '}
          {overlap.map((entry) => `${entry.service} also covers ${entry.districts.join(', ')}.`).join(' ')} Advisors will see both and compare them.
        </p>
      )}
      {message === 'saved' ? <p role="status">The coverage area is saved.</p> : null}
      {message === 'failed' ? <p role="alert">The coverage area could not be saved. Try again.</p> : null}

      <div className={styles.actions}>
        <Button variant="primary" busy={saving} onClick={() => void save()} dataEl="COV-SAVE-BTN">
          Save area
        </Button>
        <Button variant="neutral" href="/lead" dataEl="COV-CANCEL-BTN">
          Cancel
        </Button>
      </div>
    </main>
  );
}
