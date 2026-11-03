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
// The preview is the form as advisors will read it. It follows the choice as it is made; nothing is saved
// until Save. The weekend gap card of the board is not drawn: the planning coverage has no days in it.

const PROBLEMS: Record<CoverageProblem, { field: string; message: string }> = {
  districts: { field: 'cov-districts', message: 'Choose at least one district.' },
  hours: { field: 'cov-hours', message: `Enter the response target in whole hours, from 1 to ${MAX_RESPONSE_HOURS}.` },
  days: { field: 'cov-days', message: 'Choose at least one day you visit.' },
};

const DAY_NAMES: Record<DayCode, string> = {
  mon: 'Monday',
  tue: 'Tuesday',
  wed: 'Wednesday',
  thu: 'Thursday',
  fri: 'Friday',
  sat: 'Saturday',
  sun: 'Sunday',
};

type Load = { kind: 'loading' } | { kind: 'failed'; notFound: boolean } | { kind: 'ready'; form: Form };

/** "A", "A and B", "A, B and C": the words for a list. */
function listWords(items: readonly string[]): string {
  if (items.length <= 1) return items.join('');
  return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`;
}

/** The days as a person says them: "Monday to Friday" for a run of three or more, otherwise the names in order. */
function daysWords(days: readonly DayCode[]): string {
  const order = DAYS.map((day) => day.value);
  const indexes = days.map((day) => order.indexOf(day)).sort((a, b) => a - b);
  const run = indexes.every((index, i) => i === 0 || index === indexes[i - 1] + 1);
  const names = indexes.map((index) => DAY_NAMES[order[index]]);
  if (run && names.length > 2) return `${names[0]} to ${names[names.length - 1]}`;
  return listWords(names);
}

function Preview({ form, districts, days, hours }: { form: Form; districts: string[]; days: DayCode[]; hours: number | null }) {
  const headId = useId();
  const chosen = form.available.filter((district) => districts.includes(district));
  const unchosen = form.available.filter((district) => !districts.includes(district));
  // The first chosen district another service also covers, and those services: the patient the note is about.
  const shared = chosen.find((district) => form.others.some((other) => other.district === district));
  const sharedWith = [...new Set(form.others.filter((other) => other.district === shared).map((other) => other.service))];

  const visits =
    chosen.length === 0 ? 'No districts chosen yet.' : days.length === 0 ? `Visits ${listWords(chosen)}.` : `Visits ${listWords(chosen)}, ${daysWords(days)}.`;
  const responds = hours === null ? 'Set a response target to show it here.' : `Responds within about ${hours} ${hours === 1 ? 'hr' : 'hrs'}.`;
  const notOffered = unchosen.length === 0 ? null : `A patient in ${unchosen[0]} will not be offered this service.`;
  const offered =
    shared !== undefined
      ? `A patient in ${shared} will be offered this one and ${listWords(sharedWith)}.`
      : chosen.length === 0
        ? null
        : `A patient in ${chosen[0]} will be offered this one.`;

  return (
    <aside className={styles.preview} aria-label="Preview">
      <section className={styles.card} aria-labelledby={headId}>
        <h2 id={headId} className={styles.kicker}>
          How advisors will see it
        </h2>
        <div className={styles.previewBox}>
          <div className={styles.previewName}>{form.serviceName}</div>
          <p className={styles.previewLine}>{visits}</p>
          <p className={styles.previewLine}>{responds}</p>
        </div>
        <div className={styles.previewNote}>
          {notOffered === null ? null : <p>{notOffered}</p>}
          {offered === null ? null : <p>{offered}</p>}
        </div>
      </section>
    </aside>
  );
}

export function CoverageForm({ serviceId }: { serviceId: string }) {
  const id = encodeURIComponent(serviceId);
  const hoursId = useId();
  const countId = useId();
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
  const hoursValue = /^\d{1,2}$/.test(hours.trim()) ? Number(hours) : NaN;
  const previewHours = hoursValue >= 1 && hoursValue <= MAX_RESPONSE_HOURS ? hoursValue : null;

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
      <div className={styles.layout}>
        <div className={styles.formCard}>
          <ErrorSummary errors={errors} summaryRef={summary} />

          <fieldset id="cov-districts" className={styles.chips} aria-describedby={countId}>
            <legend className={styles.legend}>Districts you cover (required)</legend>
            {form.available.map((district) => (
              <Chip key={district} pressed={districts.includes(district)} onPressedChange={(on) => setDistricts((list) => toggle(list, district, on))} dataEl={`COV-DISTRICT-${district}`}>
                {district}
              </Chip>
            ))}
          </fieldset>
          <p id={countId} className={styles.count}>{`${districts.length} of ${form.available.length} districts chosen`}</p>

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

          <div role="status" className={styles.statusSlot}>
            {overlap.length === 0 ? null : (
              <div className={styles.reveal}>
                <p className={styles.overlap} data-el="COV-OVERLAP">
                  <strong>Overlap.</strong>{' '}
                  {overlap.map((entry) => `${entry.service} also covers ${entry.districts.join(', ')}.`).join(' ')} Advisors will see both and compare them.
                </p>
              </div>
            )}
          </div>
          {message === 'saved' ? <p role="status">The coverage area is saved.</p> : null}
          {message === 'failed' ? <p role="alert">The coverage area could not be saved. Try again.</p> : null}

          <div className={styles.footer}>
            <Button variant="primary" busy={saving} onClick={() => void save()} dataEl="COV-SAVE-BTN">
              Save the coverage area
            </Button>
            <Button variant="neutral" href="/lead" dataEl="COV-CANCEL-BTN">
              Cancel
            </Button>
          </div>
        </div>

        <Preview form={form} districts={districts} days={days} hours={previewHours} />
      </div>
    </main>
  );
}
