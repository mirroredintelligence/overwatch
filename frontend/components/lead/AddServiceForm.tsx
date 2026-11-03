'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { MorphStage } from '@/components/morph/MorphStage';
import { StepBar } from '@/components/morph/StepBar';
import { SummaryPin, type SummaryItem } from '@/components/morph/SummaryPin';
import { leadPost, newIdempotencyKey } from '@/lib/lead/browser';
import { districtsOf, toServiceBody, type ServiceValues } from '@/lib/lead/serviceForm';
import { ServiceAdded } from './addservice/ServiceAdded';
import { StepCheck, acceptedWords, ageWords, dateWords, lower } from './addservice/StepCheck';
import { StepCriteria } from './addservice/StepCriteria';
import { StepReporting, cadenceLabel } from './addservice/StepReporting';
import { CATEGORIES, MEASURES, StepService, labelOf } from './addservice/StepService';
import { stepOfField, useServiceFormState } from './addservice/useServiceFormState';
import styles from './addservice/StepService.module.css';

// Add a service reporter (W18, pilot; LDR-03 and LDR-04). The lead sets a service up on its behalf, in four steps
// and an added state that share one form state in memory (nothing is stored in the browser). The step is in the
// address as ?step= so Back and a reload work. "Next" checks its own step and shows a summary of problems at the
// top of it; the last step ("Check") checks them all, then posts the values as JSON with one Idempotency-Key per
// attempt, so a second press of a failed save is the same request (H-332). The added state is not an address: it
// shows while the saved service is held, and "Add another service" starts the whole form again.

const SETUP_PATH = '/lead/services/new';
const SAVE_PATH = '/api/bff/lead/services';

const STEPS = [{ label: 'The service' }, { label: 'Who reports' }, { label: 'Who it takes' }, { label: 'Check' }];

// The steps of the form (?step=1 to 4) and the added state after them.
const FORM_STEPS = STEPS.length;
const ADDED = FORM_STEPS;

// The board's three columns (list, stage, side) of each step: the summary is open from step 2 to the check.
const TEMPLATES = [
  '0px minmax(0,1fr) 0px',
  '312px minmax(0,1fr) 0px',
  '312px minmax(0,1fr) 0px',
  '312px minmax(0,1fr) 0px',
  '0px minmax(0,1fr) 0px',
];
const GAPS = ['0px', '22px', '22px', '22px', '0px'];

/** How the reporter's invitation went: sent by text, not sent, or not sent at all (an email reporter). */
type InviteResult = 'sent' | 'failed' | 'none';
type Saved = { serviceId: string | null; invite: InviteResult } | null;

const INVITE_PATH = '/api/bff/lead/invitations';

/** The text asking the reporter for the capacity figure, sent as the service is saved (DEC-1331). */
async function inviteReporter(serviceId: string | null, values: ServiceValues): Promise<InviteResult> {
  if (serviceId === null || values.channel !== 'text') return 'none';
  const result = await leadPost(
    INVITE_PATH,
    { serviceId, role: values.roleName.trim(), phone: values.mobile, channel: 'text' },
    newIdempotencyKey(),
  );
  return result.ok ? 'sent' : 'failed';
}

/** The step (from 0) in `?step=` (from 1); anything else is the first. */
function stepFrom(param: string | null): number {
  const n = Number(param);
  return Number.isInteger(n) && n >= 1 && n <= FORM_STEPS ? n - 1 : 0;
}

/** The form, started again from blank when "Add another service" is pressed. */
export function AddServiceForm() {
  const router = useRouter();
  const step = stepFrom(useSearchParams().get('step'));
  const [generation, setGeneration] = useState(0);
  const [restarting, setRestarting] = useState(false);
  // Adjusting state while rendering, as React allows: the form is replaced once the address is back on step 1.
  if (restarting && step === 0) {
    setRestarting(false);
    setGeneration(generation + 1);
  }
  return (
    <AddServiceFlow
      key={generation}
      onAddAnother={() => {
        setRestarting(true);
        router.push(`${SETUP_PATH}?step=1`);
      }}
    />
  );
}

function AddServiceFlow({ onAddAnother }: { onAddAnother: () => void }) {
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
  const [problem, setProblem] = useState('');
  const summaryRef = useRef<HTMLDivElement>(null);
  const keyRef = useRef<string | null>(null);
  // Counts the refused presses of Next or Add. Focus goes to the summary once it has rendered, not before.
  const [refusals, setRefusals] = useState(0);
  const focused = useRef(0);

  // Once the service is added the added state shows, whatever the address says.
  const view = saved !== null ? ADDED : step;

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

  async function add() {
    if (saving || saved !== null) return;
    setProblem('');
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
      const id = typeof serviceId === 'string' ? serviceId : null;
      // The reporter is asked for the capacity figure at once (DEC-1331). An email reporter is not texted here.
      const invite = await inviteReporter(id, values);
      // The added state shows with a fade, not a step: keyboard or not, the page is already on the last address.
      setInstant(false);
      setSaved({ serviceId: id, invite });
      return;
    }
    setProblem('The service could not be saved.');
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
  if (step >= 3 && values.accepts.length > 0) {
    items.push({
      key: 'criteria',
      label: 'Who it takes',
      value: acceptedWords(values),
      detail: [`age ${ageWords(values)}`, districtsOf(values.districts).join(', '), `review by ${dateWords(values.reviewBy)}`]
        .filter(Boolean)
        .join(' · '),
    });
  }
  const goToKey = (key: string) => back(key === 'service' ? 0 : key === 'reporting' ? 1 : 2);

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
      <StepCriteria
        values={values}
        set={form.set}
        toggle={form.toggle}
        errors={errorsOf(2)}
        summaryRef={summaryRef}
        onNext={(viaKeyboard) => next(2, viaKeyboard)}
        onBack={() => back(1)}
      />
    ),
    () => (
      <StepCheck
        values={values}
        onChange={(index) => back(index)}
        onBack={() => back(2)}
        onAdd={() => void add()}
        busy={saving}
        problem={problem}
      />
    ),
    () => (
      <ServiceAdded
        name={values.name.trim()}
        serviceId={saved?.serviceId ?? null}
        invite={saved?.invite ?? 'none'}
        onAddAnother={onAddAnother}
      />
    ),
  ];

  const pinned = view >= 1 && view < ADDED && items.length > 0;
  return (
    <main className={styles.page} data-step={view}>
      {view < ADDED ? (
        <div className={styles.bar}>
          <StepBar label="Setup steps" steps={STEPS} current={step} reached={reached} onSelect={(index) => back(index)} />
        </div>
      ) : null}
      {view < ADDED ? (
        <div className={styles.pill}>
          <SummaryPin variant="pill" items={items} onChange={goToKey} />
        </div>
      ) : null}
      <MorphStage
        label="Setup stage"
        className={styles.stage}
        current={view}
        templates={TEMPLATES}
        gaps={GAPS}
        instant={instant}
        layers={layers}
        summary={<SummaryPin items={items} onChange={goToKey} open={pinned} />}
      />
    </main>
  );
}
