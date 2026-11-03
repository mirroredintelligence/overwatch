'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { MorphStage } from '@/components/morph/MorphStage';
import { StepBar } from '@/components/morph/StepBar';
import { SummaryPin, type SummaryItem } from '@/components/morph/SummaryPin';
import { Button } from '@/components/ui/Button';
import { leadPost, newIdempotencyKey } from '@/lib/lead/browser';
import { toServiceBody } from '@/lib/lead/serviceForm';
import { StepReporting, cadenceLabel } from './addservice/StepReporting';
import { CATEGORIES, ChoiceGroup, Field, MEASURES, StepFrame, StepService, labelOf } from './addservice/StepService';
import { STEP_COUNT, stepOfField, useServiceFormState } from './addservice/useServiceFormState';
import styles from './addservice/StepService.module.css';

// Add a service reporter (W18, pilot; LDR-03). The lead sets a service up on its behalf, in steps that share one
// form state in memory (nothing is stored in the browser). The step is in the address as ?step= so Back and a
// reload work. "Next" checks its own step and shows a summary of problems at the top of it; the last step checks
// them all, then posts the values as JSON with one Idempotency-Key per attempt, so a second press of a failed
// save is the same request (H-332). Steps 3 and 4 (Check and Added) are built by LDR-04: for now the third step
// still ends in Save.

const SETUP_PATH = '/lead/services/new';
const SAVE_PATH = '/api/bff/lead/services';

// The steps built so far, and the board's words for them.
const STEPS = [{ label: 'The service' }, { label: 'Who reports' }, { label: 'Who it takes' }];

// The board's three columns (list, stage, side) of each step: the summary opens from step 2.
const TEMPLATES = ['0px minmax(0,1fr) 0px', '312px minmax(0,1fr) 0px', '312px minmax(0,1fr) 0px'];
const GAPS = ['0px', '22px', '22px'];

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

type Saved = { serviceId: string } | null;

const lower = (text: string) => (text === '' ? '' : `${text.charAt(0).toLowerCase()}${text.slice(1)}`);

/** The step (from 0) in `?step=` (from 1); anything else is the first. */
function stepFrom(param: string | null): number {
  const n = Number(param);
  return Number.isInteger(n) && n >= 1 && n <= STEP_COUNT ? n - 1 : 0;
}

export function AddServiceForm() {
  const router = useRouter();
  const step = stepFrom(useSearchParams().get('step'));
  const form = useServiceFormState();
  const { values } = form;

  const [reached, setReached] = useState(step);
  // Adjusting state while rendering, as React allows: the furthest step reached only grows.
  if (step > reached) setReached(step);
  const [instant, setInstant] = useState(false);

  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<Saved>(null);
  const [notice, setNotice] = useState('');
  const [noticeIsError, setNoticeIsError] = useState(false);
  const summaryRef = useRef<HTMLDivElement>(null);
  const keyRef = useRef<string | null>(null);
  // Counts the refused presses of Next or Save. Focus goes to the summary once it has rendered, not before.
  const [refusals, setRefusals] = useState(0);
  const focused = useRef(0);

  useEffect(() => {
    if (refusals > focused.current && summaryRef.current) {
      focused.current = refusals;
      summaryRef.current.focus();
    }
  }, [refusals, step, form.errors]);

  function goTo(index: number, viaKeyboard = false) {
    setInstant(viaKeyboard);
    router.push(`${SETUP_PATH}?step=${index + 1}`);
  }

  function back(index: number) {
    form.clearErrors();
    goTo(index);
  }

  function next(from: number, viaKeyboard: boolean) {
    if (form.check(from).length > 0) {
      setRefusals((count) => count + 1);
      return;
    }
    goTo(from + 1, viaKeyboard);
  }

  async function save() {
    if (saving) return;
    setNotice('');
    const first = form.checkAll();
    if (first !== null) {
      setRefusals((count) => count + 1);
      if (first !== step) goTo(first, true);
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

  // The problems of one check are all on one step; they are shown only there.
  const errorStep = form.errors.length > 0 ? stepOfField(form.errors[0].field) : -1;
  const errorsOf = (index: number) => (index === errorStep ? form.errors : []);

  const items: SummaryItem[] = [];
  if (step >= 1 && values.name.trim() !== '') {
    items.push({
      key: 'service',
      label: 'The service',
      value: values.name.trim(),
      detail: [
        labelOf(CATEGORIES, values.category),
        values.measure ? `counts ${lower(labelOf(MEASURES, values.measure))}` : '',
        values.establishedCapacity.trim() ? `${values.establishedCapacity.trim()} established` : '',
      ]
        .filter(Boolean)
        .join(' · '),
    });
  }
  if (step >= 2 && values.roleName.trim() !== '') {
    items.push({
      key: 'reporting',
      label: 'Who reports',
      value: `${values.roleName.trim()}, by ${values.channel}`,
      detail: [
        // Only the last four digits of a number are ever shown again.
        values.channel === 'text' ? `Phone ending ${values.mobile.replace(/\D/g, '').slice(-4)}` : '',
        lower(cadenceLabel(values.cadence)),
      ]
        .filter(Boolean)
        .join(' · '),
    });
  }
  const goToKey = (key: string) => back(key === 'service' ? 0 : 1);

  const layers = [
    () => (
      <StepService
        values={values}
        set={form.set}
        errors={errorsOf(0)}
        summaryRef={summaryRef}
        onNext={(viaKeyboard) => next(0, viaKeyboard)}
      />
    ),
    () => (
      <StepReporting
        values={values}
        set={form.set}
        errors={errorsOf(1)}
        summaryRef={summaryRef}
        onNext={(viaKeyboard) => next(1, viaKeyboard)}
        onBack={() => back(0)}
      />
    ),
    () => (
      <StepFrame
        title="Who it takes"
        errors={errorsOf(2)}
        summaryRef={summaryRef}
        onNext={() => void save()}
        onBack={() => back(1)}
        nextLabel="Save"
        busy={saving}
        dataEl="LEAD-ADD-SAVE-BTN"
        secondary={
          <Button variant="secondary" disabled={saved === null} onClick={() => void testPrompt()} dataEl="LEAD-ADD-TEST-BTN">
            Send a test prompt
          </Button>
        }
      >
        <ChoiceGroup
          id="lead-add-accepts"
          label="Needs you accept"
          choices={ACCEPTS}
          selected={values.accepts}
          onPick={(value) => form.toggle('accepts', value)}
          idPrefix="LEAD-ADD-ACCEPTS"
          error={errorsOf(2).find((e) => e.field === 'lead-add-accepts')?.message}
        />
        <ChoiceGroup
          label="Needs you do not accept"
          choices={EXCLUDES}
          selected={values.excludes}
          onPick={(value) => form.toggle('excludes', value)}
          idPrefix="LEAD-ADD-EXCLUDES"
        />
        <Field id="lead-add-age-min" label="Youngest age" error={errorsOf(2).find((e) => e.field === 'lead-add-age-min')?.message}>
          {(props) => <input {...props} inputMode="numeric" value={values.ageMin} onChange={(e) => form.set('ageMin', e.target.value)} />}
        </Field>
        <Field
          id="lead-add-age-max"
          label="Oldest age"
          hint="Leave blank for no limit"
          error={errorsOf(2).find((e) => e.field === 'lead-add-age-max')?.message}
        >
          {(props) => <input {...props} inputMode="numeric" value={values.ageMax} onChange={(e) => form.set('ageMax', e.target.value)} />}
        </Field>
        <Field
          id="lead-add-districts"
          label="Postcode districts"
          hint="Like DT4. Separate with commas."
          error={errorsOf(2).find((e) => e.field === 'lead-add-districts')?.message}
        >
          {(props) => <input {...props} value={values.districts} onChange={(e) => form.set('districts', e.target.value)} />}
        </Field>
        <Field
          id="lead-add-review"
          label="Review criteria by"
          hint="Advisors see a flag when this date passes"
          error={errorsOf(2).find((e) => e.field === 'lead-add-review')?.message}
        >
          {(props) => <input {...props} type="date" value={values.reviewBy} onChange={(e) => form.set('reviewBy', e.target.value)} />}
        </Field>
        <p className={styles.pilot}>Services with neither text nor email are outside the MVP.</p>
        <p role="status" className={styles.status}>
          {noticeIsError ? '' : notice}
        </p>
        {noticeIsError && notice !== '' ? (
          <p role="alert" className={styles.problem}>
            {notice}
          </p>
        ) : null}
      </StepFrame>
    ),
  ];

  return (
    <main className={styles.page} data-step={step}>
      <div className={styles.bar}>
        <StepBar label="Setup steps" steps={STEPS} current={step} reached={reached} onSelect={(index) => back(index)} />
      </div>
      <div className={styles.pill}>
        <SummaryPin variant="pill" items={items} onChange={goToKey} />
      </div>
      <MorphStage
        label="Setup stage"
        className={styles.stage}
        current={step}
        templates={TEMPLATES}
        gaps={GAPS}
        instant={instant}
        layers={layers}
        summary={<SummaryPin items={items} onChange={goToKey} open={step >= 1 && items.length > 0} />}
      />
    </main>
  );
}
