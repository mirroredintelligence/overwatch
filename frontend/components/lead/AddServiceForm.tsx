'use client';

import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { ErrorSummary, type FieldError } from '@/components/lead/ErrorSummary';
import { Button } from '@/components/ui/Button';
import { Chip } from '@/components/ui/Chip';
import { leadPost, newIdempotencyKey } from '@/lib/lead/browser';
import { blankService, toServiceBody, validateService, type ServiceValues } from '@/lib/lead/serviceForm';
import styles from './Lead.module.css';

// Add a service reporter (W18, pilot). The lead sets a service up on its behalf. The form checks what it
// can at once, shows a summary with a link to each problem, and posts the values as JSON with one
// Idempotency-Key per attempt, so a second press of a failed save is the same request (H-332).

const CATEGORIES: [string, string][] = [
  ['urgent-community-response', 'Urgent community response'],
  ['same-day-emergency-care', 'Same day emergency care'],
  ['inpatient-beds', 'Inpatient beds'],
  ['hospital-at-home-or-virtual-ward', 'Hospital at home or virtual ward'],
  ['reablement', 'Reablement'],
  ['other', 'Other'],
];

// "Virtual beds free" is the same measure as "Beds free" (free-beds); the unit label carries the
// difference. The screen offers the four measures the back end counts (DEC-655).
const MEASURES: [string, string][] = [
  ['referrals-acceptable', 'Referrals in the next 2 hrs'],
  ['free-beds', 'Beds free'],
  ['free-slots', 'Slots left today'],
  ['packages-free', 'Packages available'],
];

const CADENCES: [string, string][] = [
  ['every-2-hrs', 'Every 2 hrs'],
  ['twice-a-day', 'Twice a day'],
  ['once-a-day', 'Once a day'],
];

const ACCEPTS: [string, string][] = [
  ['fall-no-injury', 'Fall, no injury'],
  ['frailty', 'Frailty'],
  ['wound-care', 'Wound care'],
  ['iv-therapy', 'IV therapy'],
  ['palliative', 'Palliative'],
  ['dementia', 'Dementia'],
];

const EXCLUDES: [string, string][] = [
  ['suspected-fracture', 'Suspected fracture'],
  ['head-injury-anticoagulants', 'Head injury on anticoagulants'],
  ['iv-therapy', 'Needs IV therapy'],
  ['infection-isolation', 'Infection isolation'],
];

const SAVE_PATH = '/api/bff/lead/services';

type Saved = { serviceId: string } | null;

function toggle(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((item) => item !== value) : [...list, value];
}

function ChoiceGroup({
  label,
  choices,
  selected,
  onPick,
  idPrefix,
}: {
  label: string;
  choices: [string, string][];
  selected: string | null;
  onPick: (value: string) => void;
  idPrefix: string;
}) {
  const labelId = useId();
  return (
    <div role="group" aria-labelledby={labelId} className={styles.choices} data-el={`${idPrefix}-GROUP`}>
      <p id={labelId} className={styles.fieldLabel}>
        {label}
      </p>
      <div className={styles.chipRow}>
        {choices.map(([value, text]) => (
          <Chip
            key={value}
            pressed={selected === value}
            onPressedChange={() => onPick(value)}
            dataEl={`${idPrefix}-${value.toUpperCase()}`}
          >
            {text}
          </Chip>
        ))}
      </div>
    </div>
  );
}

function MultiGroup({
  label,
  choices,
  selected,
  onToggle,
  idPrefix,
}: {
  label: string;
  choices: [string, string][];
  selected: string[];
  onToggle: (value: string) => void;
  idPrefix: string;
}) {
  const labelId = useId();
  return (
    <div role="group" aria-labelledby={labelId} className={styles.choices} data-el={`${idPrefix}-GROUP`}>
      <p id={labelId} className={styles.fieldLabel}>
        {label}
      </p>
      <div className={styles.chipRow}>
        {choices.map(([value, text]) => (
          <Chip
            key={value}
            pressed={selected.includes(value)}
            onPressedChange={() => onToggle(value)}
            dataEl={`${idPrefix}-${value.toUpperCase()}`}
          >
            {text}
          </Chip>
        ))}
      </div>
    </div>
  );
}

function Field({
  id,
  label,
  hint,
  error,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  children: (describedBy: string | undefined) => ReactNode;
}) {
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const describedBy = [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(' ') || undefined;
  return (
    <div className={styles.field}>
      <label htmlFor={id} className={styles.fieldLabel}>
        {label}
      </label>
      {hint ? (
        <p id={hintId} className={styles.muted}>
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} className={styles.fieldError}>
          {error}
        </p>
      ) : null}
      {children(describedBy)}
    </div>
  );
}

export function AddServiceForm() {
  const [values, setValues] = useState<ServiceValues>(blankService);
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<Saved>(null);
  const [notice, setNotice] = useState('');
  const [noticeIsError, setNoticeIsError] = useState(false);
  const summaryRef = useRef<HTMLDivElement>(null);
  const keyRef = useRef<string | null>(null);
  // Counts the refused submits. Focus goes to the summary once it has rendered, not before.
  const [refusals, setRefusals] = useState(0);

  useEffect(() => {
    if (refusals > 0) summaryRef.current?.focus();
  }, [refusals]);

  const set = <K extends keyof ServiceValues>(key: K, value: ServiceValues[K]) =>
    setValues((previous) => ({ ...previous, [key]: value }));

  const errorFor = (field: string) => errors.find((error) => error.field === field)?.message;

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving) return;
    const problems = validateService(values, Date.now());
    setErrors(problems);
    setNotice('');
    if (problems.length > 0) {
      setRefusals((count) => count + 1);
      return;
    }
    keyRef.current ??= newIdempotencyKey();
    setSaving(true);
    const result = await leadPost(SAVE_PATH, toServiceBody(values), keyRef.current);
    setSaving(false);
    if (result.ok) {
      keyRef.current = null;
      const serviceId = (result.body as { serviceId?: unknown } | undefined)?.serviceId;
      setSaved(typeof serviceId === 'string' ? { serviceId } : null);
      setNoticeIsError(false);
      setNotice('Saved');
      return;
    }
    setNoticeIsError(true);
    setNotice('The service could not be saved.');
  }

  async function testPrompt() {
    if (saved === null) return;
    const result = await leadPost(`/api/bff/lead/services/${encodeURIComponent(saved.serviceId)}/test-prompt`);
    setNoticeIsError(!result.ok);
    setNotice(result.ok ? 'Test prompt sent.' : 'The test prompt could not be sent.');
  }

  return (
    <main className={styles.page}>
      <header className={styles.stack}>
        <p className={styles.muted}>Onboarding</p>
        <h1 className={styles.title}>Add a service reporter</h1>
      </header>

      <ErrorSummary errors={errors} summaryRef={summaryRef} />

      <form onSubmit={(event) => void save(event)} noValidate className={styles.stack}>
        <section className={styles.section} aria-labelledby="add-service-heading">
          <h2 id="add-service-heading" className={styles.sectionHeading}>
            Service
          </h2>
          <Field id="lead-add-name" label="Service name" error={errorFor('lead-add-name')}>
            {(describedBy) => (
              <input
                id="lead-add-name"
                className={styles.input}
                value={values.name}
                onChange={(e) => set('name', e.target.value)}
                aria-describedby={describedBy}
              />
            )}
          </Field>
          <ChoiceGroup
            label="Category"
            choices={CATEGORIES}
            selected={values.category}
            onPick={(value) => set('category', value)}
            idPrefix="LEAD-ADD-CATEGORY"
          />
          {errorFor('lead-add-category') ? <p id="lead-add-category" className={styles.fieldError}>{errorFor('lead-add-category')}</p> : null}
          <Field
            id="lead-add-unit"
            label="Unit label"
            hint="For example referrals in the next 2 hrs"
            error={errorFor('lead-add-unit')}
          >
            {(describedBy) => (
              <input
                id="lead-add-unit"
                className={styles.input}
                value={values.unitLabel}
                onChange={(e) => set('unitLabel', e.target.value)}
                aria-describedby={describedBy}
              />
            )}
          </Field>
          <ChoiceGroup
            label="What is counted"
            choices={MEASURES}
            selected={values.measure}
            onPick={(value) => set('measure', value)}
            idPrefix="LEAD-ADD-MEASURE"
          />
          {errorFor('lead-add-measure') ? <p className={styles.fieldError}>{errorFor('lead-add-measure')}</p> : null}
          <Field id="lead-add-established" label="Established capacity" error={errorFor('lead-add-established')}>
            {(describedBy) => (
              <input
                id="lead-add-established"
                className={styles.input}
                inputMode="numeric"
                value={values.establishedCapacity}
                onChange={(e) => set('establishedCapacity', e.target.value)}
                aria-describedby={describedBy}
              />
            )}
          </Field>
          <div className={styles.pair}>
            <Field id="lead-add-usual-min" label="Lowest usual number" error={errorFor('lead-add-usual-min')}>
              {(describedBy) => (
                <input
                  id="lead-add-usual-min"
                  className={styles.input}
                  inputMode="numeric"
                  value={values.usualMin}
                  onChange={(e) => set('usualMin', e.target.value)}
                  aria-describedby={describedBy}
                />
              )}
            </Field>
            <Field id="lead-add-usual-max" label="Highest usual number" error={errorFor('lead-add-usual-max')}>
              {(describedBy) => (
                <input
                  id="lead-add-usual-max"
                  className={styles.input}
                  inputMode="numeric"
                  value={values.usualMax}
                  onChange={(e) => set('usualMax', e.target.value)}
                  aria-describedby={describedBy}
                />
              )}
            </Field>
          </div>
          <p className={styles.muted}>Accepts referrals every day, from the From time to the To time.</p>
          <div className={styles.pair}>
            <Field id="lead-add-from" label="From" error={errorFor('lead-add-from')}>
              {(describedBy) => (
                <input
                  id="lead-add-from"
                  className={styles.input}
                  placeholder="08:00"
                  value={values.availableFrom}
                  onChange={(e) => set('availableFrom', e.target.value)}
                  aria-describedby={describedBy}
                />
              )}
            </Field>
            <Field id="lead-add-to" label="To" error={errorFor('lead-add-to')}>
              {(describedBy) => (
                <input
                  id="lead-add-to"
                  className={styles.input}
                  placeholder="20:00"
                  value={values.availableTo}
                  onChange={(e) => set('availableTo', e.target.value)}
                  aria-describedby={describedBy}
                />
              )}
            </Field>
          </div>
        </section>

        <section className={styles.section} aria-labelledby="add-reporting-heading">
          <h2 id="add-reporting-heading" className={styles.sectionHeading}>
            Reporting
          </h2>
          <ChoiceGroup
            label="How will they report?"
            choices={[
              ['text', 'Text'],
              ['email', 'Email'],
            ]}
            selected={values.channel}
            onPick={(value) => set('channel', value as 'text' | 'email')}
            idPrefix="LEAD-ADD-CHANNEL"
          />
          {values.channel === 'text' ? (
            <Field id="lead-add-mobile" label="Mobile number for text" hint="A ward or team phone is best." error={errorFor('lead-add-mobile')}>
              {(describedBy) => (
                <input
                  id="lead-add-mobile"
                  className={styles.input}
                  inputMode="tel"
                  autoComplete="off"
                  value={values.mobile}
                  onChange={(e) => set('mobile', e.target.value)}
                  aria-describedby={describedBy}
                />
              )}
            </Field>
          ) : (
            <Field id="lead-add-email" label="Email" error={errorFor('lead-add-email')}>
              {(describedBy) => (
                <input
                  id="lead-add-email"
                  className={styles.input}
                  type="email"
                  autoComplete="off"
                  value={values.email}
                  onChange={(e) => set('email', e.target.value)}
                  aria-describedby={describedBy}
                />
              )}
            </Field>
          )}
          <Field id="lead-add-role" label="Who holds this phone" hint="For example duty manager" error={errorFor('lead-add-role')}>
            {(describedBy) => (
              <input
                id="lead-add-role"
                className={styles.input}
                value={values.roleName}
                onChange={(e) => set('roleName', e.target.value)}
                aria-describedby={describedBy}
              />
            )}
          </Field>
          <ChoiceGroup
            label="Usual cadence"
            choices={CADENCES}
            selected={values.cadence}
            onPick={(value) => set('cadence', value)}
            idPrefix="LEAD-ADD-CADENCE"
          />
          {errorFor('lead-add-cadence') ? <p className={styles.fieldError}>{errorFor('lead-add-cadence')}</p> : null}
        </section>

        <section className={styles.section} aria-labelledby="add-criteria-heading">
          <h2 id="add-criteria-heading" className={styles.sectionHeading}>
            Criteria version 1
          </h2>
          <MultiGroup
            label="Needs you accept"
            choices={ACCEPTS}
            selected={values.accepts}
            onToggle={(value) => set('accepts', toggle(values.accepts, value))}
            idPrefix="LEAD-ADD-ACCEPTS"
          />
          {errorFor('lead-add-accepts') ? <p id="lead-add-accepts" className={styles.fieldError}>{errorFor('lead-add-accepts')}</p> : null}
          <MultiGroup
            label="Needs you do not accept"
            choices={EXCLUDES}
            selected={values.excludes}
            onToggle={(value) => set('excludes', toggle(values.excludes, value))}
            idPrefix="LEAD-ADD-EXCLUDES"
          />
          <div className={styles.pair}>
            <Field id="lead-add-age-min" label="Youngest age" error={errorFor('lead-add-age-min')}>
              {(describedBy) => (
                <input
                  id="lead-add-age-min"
                  className={styles.input}
                  inputMode="numeric"
                  value={values.ageMin}
                  onChange={(e) => set('ageMin', e.target.value)}
                  aria-describedby={describedBy}
                />
              )}
            </Field>
            <Field id="lead-add-age-max" label="Oldest age" hint="Leave blank for no limit" error={errorFor('lead-add-age-max')}>
              {(describedBy) => (
                <input
                  id="lead-add-age-max"
                  className={styles.input}
                  inputMode="numeric"
                  value={values.ageMax}
                  onChange={(e) => set('ageMax', e.target.value)}
                  aria-describedby={describedBy}
                />
              )}
            </Field>
          </div>
          <Field
            id="lead-add-districts"
            label="Postcode districts"
            hint="Like DT4. Separate with commas."
            error={errorFor('lead-add-districts')}
          >
            {(describedBy) => (
              <input
                id="lead-add-districts"
                className={styles.input}
                value={values.districts}
                onChange={(e) => set('districts', e.target.value)}
                aria-describedby={describedBy}
              />
            )}
          </Field>
          <Field id="lead-add-review" label="Review criteria by" hint="Advisors see a flag when this date passes" error={errorFor('lead-add-review')}>
            {(describedBy) => (
              <input
                id="lead-add-review"
                className={styles.input}
                type="date"
                value={values.reviewBy}
                onChange={(e) => set('reviewBy', e.target.value)}
                aria-describedby={describedBy}
              />
            )}
          </Field>
        </section>

        <p className={styles.muted}>Services with neither text nor email are outside the MVP.</p>

        <div className={styles.actions}>
          <Button variant="primary" type="submit" busy={saving} dataEl="LEAD-ADD-SAVE-BTN">
            Save
          </Button>
          <Button
            variant="secondary"
            disabled={saved === null}
            onClick={() => void testPrompt()}
            dataEl="LEAD-ADD-TEST-BTN"
          >
            Send a test prompt
          </Button>
        </div>
      </form>

      <p role="status" className={noticeIsError ? styles.muted : styles.line}>
        {noticeIsError ? '' : notice}
      </p>
      {noticeIsError && notice !== '' ? <p role="alert" className={styles.fieldError}>{notice}</p> : null}
    </main>
  );
}
