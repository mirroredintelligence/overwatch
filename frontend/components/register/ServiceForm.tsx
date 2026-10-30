'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Chip } from '@/components/ui/Chip';
import { ChipGroup } from '@/components/forms/ChipGroup';
import { ErrorSummary } from '@/components/forms/ErrorSummary';
import { TextField } from '@/components/forms/TextField';
import { loadRegistration, saveStep, sessionCsrf, type StepOutcome } from '@/lib/register/browser';
import {
  DAY_OPTIONS,
  EXCLUDED_NEED_OPTIONS,
  NEED_OPTIONS,
  NO_EXCLUSIONS,
  type Option,
  REFERRAL_METHODS,
  SERVICE_CATEGORIES,
} from '@/lib/register/options';
import { normaliseDistrict, validateService, type ServiceAnswers } from '@/lib/register/service';
import type { FieldIssue } from '@/lib/register/types';
import styles from './register.module.css';

// Registration step 3, describing the service and who it is for (W25, artboards RegisterFlow2
// panels 5 and 6). The service's name is set by the shift lead and is read-only here. Continue checks every
// answer here and the back end checks them again on save.

export type ServiceFormProps = { registrationId: string };

type Load = { kind: 'loading' } | { kind: 'open'; serviceName: string; fixedSite: boolean | undefined } | { kind: 'unavailable' } | { kind: 'signed-out' };

const LOAD_FAILED = 'We could not load your registration. Try again later.';
const SIGNED_OUT = 'Please sign in again.';
const NOT_SAVED = 'Your draft is not saved. Finish the answers shown, then save again.';
const SAVED = 'Draft saved.';
const DISTRICT_FORMAT = 'Enter postcode districts, for example DT4';
const DISTRICT_DEFAULTS: readonly Option[] = ['DT1', 'DT2', 'DT3', 'DT4'].map((code) => ({ value: code, label: code }));
const EXCLUSION_OPTIONS: readonly Option[] = [...EXCLUDED_NEED_OPTIONS, { value: NO_EXCLUSIONS, label: 'No exclusions' }];

function errorFor(errors: FieldIssue[], field: string): string | null {
  return errors.find((issue) => issue.field === field)?.message ?? null;
}

/** Today's date in London, as the review date is compared with it. */
function londonToday(): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/London', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
}

function bodyFrom(answers: ServiceAnswers): Record<string, unknown> {
  const oldest = answers.ageMax === null ? null : answers.ageMax?.trim() ?? '';
  const body: Record<string, unknown> = {
    category: answers.category,
    referralMethods: answers.referralMethods,
    spoaPhone: answers.spoaPhone?.trim(),
    acceptingDays: answers.acceptingDays,
    acceptingStart: answers.acceptingStart,
    acceptingEnd: answers.acceptingEnd,
    needs: answers.needs,
    ageMin: answers.ageMin?.trim() === '' || answers.ageMin === undefined ? undefined : Number(answers.ageMin),
    ageMax: oldest === null ? null : oldest === '' ? undefined : Number(oldest),
    noExclusions: answers.noExclusions === true ? true : undefined,
    excludedNeeds: answers.noExclusions === true ? undefined : answers.excludedNeeds,
    ownerRole: answers.ownerRole?.trim(),
    ownerEmail: answers.ownerEmail?.trim(),
    reviewBy: answers.reviewBy,
    districts: answers.districts,
  };
  for (const key of Object.keys(body)) if (body[key] === undefined) delete body[key];
  return body;
}

export function ServiceForm({ registrationId }: ServiceFormProps) {
  const router = useRouter();
  const [load, setLoad] = useState<Load>({ kind: 'loading' });
  const [csrf, setCsrf] = useState<string | null>(null);
  const [answers, setAnswers] = useState<ServiceAnswers>({});
  const [errors, setErrors] = useState<FieldIssue[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<'continue' | 'save' | null>(null);
  const [districts, setDistricts] = useState<readonly Option[]>(DISTRICT_DEFAULTS);
  const [addDistrict, setAddDistrict] = useState('');
  const [addError, setAddError] = useState<string | null>(null);
  const [noLimit, setNoLimit] = useState(false);
  const [appointment, setAppointment] = useState<string[]>([]);
  const [notes, setNotes] = useState('');
  const [specialty, setSpecialty] = useState('');

  useEffect(() => {
    let alive = true;
    void (async () => {
      const [outcome, token] = await Promise.all([loadRegistration(registrationId), sessionCsrf()]);
      if (!alive) return;
      setCsrf(token);
      if (outcome.kind === 'open') {
        const fixed = outcome.view.steps.location?.fixedSite;
        setLoad({ kind: 'open', serviceName: outcome.view.serviceName, fixedSite: typeof fixed === 'boolean' ? fixed : undefined });
      } else {
        setLoad({ kind: outcome.kind });
      }
    })();
    return () => {
      alive = false;
    };
  }, [registrationId]);

  async function save(mode: 'continue' | 'save', fixedSite: boolean | undefined) {
    if (csrf === null) {
      setNotice(SIGNED_OUT);
      return;
    }
    setBusy(mode);
    setNotice(null);
    const outcome: StepOutcome = await saveStep(registrationId, 'service', bodyFrom(answers), csrf);
    setBusy(null);
    void fixedSite;
    if (outcome.kind === 'saved') {
      setErrors([]);
      if (mode === 'continue') router.push(`/register/${encodeURIComponent(registrationId)}/reporting`);
      else setNotice(SAVED);
      return;
    }
    if (outcome.kind === 'errors') {
      setErrors(outcome.errors);
      setNotice(outcome.errors.length === 0 ? LOAD_FAILED : mode === 'save' ? NOT_SAVED : null);
      return;
    }
    setNotice(LOAD_FAILED);
  }

  const header = (
    <>
      <p className={styles.product}>DIUCS capacity</p>
      <p className={styles.note}>Step 3 of 5 · Service</p>
      <h1 className={styles.heading}>Describe the service</h1>
    </>
  );

  if (load.kind === 'loading') return <div className={styles.stack}>{header}<p className={styles.text}>Loading your registration.</p></div>;
  if (load.kind !== 'open') {
    return (
      <div className={styles.stack}>
        {header}
        <p className={styles.notice} role="status">{load.kind === 'signed-out' ? SIGNED_OUT : LOAD_FAILED}</p>
      </div>
    );
  }

  const fixedSite = load.fixedSite;
  const set = <K extends keyof ServiceAnswers>(key: K, value: ServiceAnswers[K]) => setAnswers((current) => ({ ...current, [key]: value }));
  const visiting = fixedSite === false;

  return (
    <div className={styles.stack}>
      {header}
      <form
        className={styles.stack}
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          const issues = validateService(answers, { fixedSite, today: londonToday() });
          setErrors(issues);
          setNotice(null);
          if (issues.length === 0) void save('continue', fixedSite);
        }}
      >
        <ErrorSummary errors={errors} />
        <TextField id="serviceName" label="Service name" value={load.serviceName} onChange={() => undefined} requirement="none" readOnly hint="The name advisors see, for example “UCR West”" />
        <ChipGroup
          id="category"
          legend="Category"
          options={SERVICE_CATEGORIES}
          selected={answers.category === undefined ? [] : [answers.category]}
          onChange={(next) => set('category', next[0])}
          requirement="required"
          error={errorFor(errors, 'category')}
          dataEl="REG-STEP3-CATEGORY"
        />
        <TextField id="specialty" label="Specialty" value={specialty} onChange={setSpecialty} requirement="optional" />
        <ChipGroup
          id="referralMethods"
          legend="How can the coordination team refer?"
          options={REFERRAL_METHODS}
          selected={answers.referralMethods ?? []}
          multiple
          onChange={(next) => set('referralMethods', next)}
          requirement="required"
          error={errorFor(errors, 'referralMethods')}
        />
        <TextField
          id="spoaPhone"
          label="Phone number for the coordination team to call"
          value={answers.spoaPhone ?? ''}
          onChange={(value) => set('spoaPhone', value)}
          type="tel"
          inputMode="tel"
          hint="Staffed while you accept referrals"
          error={errorFor(errors, 'spoaPhone')}
          dataEl="REG-STEP3-PHONE-FIELD"
        />
        <ChipGroup
          id="acceptingDays"
          legend="Days you accept referrals"
          options={DAY_OPTIONS}
          selected={answers.acceptingDays ?? []}
          multiple
          onChange={(next) => set('acceptingDays', next)}
          requirement="required"
          error={errorFor(errors, 'acceptingDays')}
        />
        <div className={styles.stack}>
          <TextField id="acceptingStart" label="From" value={answers.acceptingStart ?? ''} onChange={(value) => set('acceptingStart', value)} hint="HH:MM" error={errorFor(errors, 'acceptingStart')} />
          <TextField id="acceptingEnd" label="To" value={answers.acceptingEnd ?? ''} onChange={(value) => set('acceptingEnd', value)} hint="HH:MM" error={errorFor(errors, 'acceptingEnd')} />
        </div>

        <h2 className={styles.subheading}>Who it is for</h2>
        <ChipGroup id="needs" legend="Needs you accept" options={NEED_OPTIONS} selected={answers.needs ?? []} multiple onChange={(next) => set('needs', next)} requirement="required" error={errorFor(errors, 'needs')} />
        <TextField id="ageMin" label="Youngest age" value={answers.ageMin ?? ''} onChange={(value) => set('ageMin', value)} inputMode="numeric" hint="From 0 to 120" error={errorFor(errors, 'ageMin')} />
        <div className={styles.stack}>
          <TextField
            id="ageMax"
            label="Oldest age"
            value={noLimit ? '' : answers.ageMax ?? ''}
            onChange={(value) => {
              setNoLimit(false);
              set('ageMax', value);
            }}
            readOnly={noLimit}
            inputMode="numeric"
            error={errorFor(errors, 'ageMax')}
          />
          <Chip
            pressed={noLimit}
            onPressedChange={(pressed) => {
              setNoLimit(pressed);
              set('ageMax', pressed ? null : '');
            }}
            dataEl="REG-STEP3-NOLIMIT"
          >
            No limit
          </Chip>
        </div>
        <ChipGroup
          id="excludedNeeds"
          legend="Needs you do not accept"
          options={EXCLUSION_OPTIONS}
          selected={answers.noExclusions === true ? [NO_EXCLUSIONS] : answers.excludedNeeds ?? []}
          multiple
          onChange={(next) => {
            if (next.includes(NO_EXCLUSIONS) && answers.noExclusions !== true) {
              setAnswers((current) => ({ ...current, noExclusions: true, excludedNeeds: [] }));
              return;
            }
            setAnswers((current) => ({ ...current, noExclusions: false, excludedNeeds: next.filter((value) => value !== NO_EXCLUSIONS) }));
          }}
          requirement="required"
          error={errorFor(errors, 'excludedNeeds')}
        />
        <TextField id="ownerRole" label="Criteria owner (role)" value={answers.ownerRole ?? ''} onChange={(value) => set('ownerRole', value)} error={errorFor(errors, 'ownerRole')} />
        <TextField id="ownerEmail" label="Owner email" value={answers.ownerEmail ?? ''} onChange={(value) => set('ownerEmail', value)} type="email" autoComplete="email" error={errorFor(errors, 'ownerEmail')} />
        <TextField id="reviewBy" label="Review criteria by" value={answers.reviewBy ?? ''} onChange={(value) => set('reviewBy', value)} type="date" hint="Advisors see a flag when this date passes" error={errorFor(errors, 'reviewBy')} />

        <div className={styles.stack}>
          <ChipGroup
            id="districts"
            legend="Area you cover (postcode districts)"
            options={districts}
            selected={answers.districts ?? []}
            multiple
            requirement={visiting ? 'required' : 'optional'}
            onChange={(next) => set('districts', next)}
            error={errorFor(errors, 'districts')}
          />
          <div className={styles.actions}>
            <TextField id="addDistrict" label="Add district" value={addDistrict} onChange={(value) => { setAddDistrict(value); setAddError(null); }} requirement="none" error={addError} />
            <Button
              variant="secondary"
              dataEl="REG-STEP3-ADD-DISTRICT"
              onClick={() => {
                const code = normaliseDistrict(addDistrict);
                if (code === null) {
                  setAddError(DISTRICT_FORMAT);
                  return;
                }
                if (!districts.some((option) => option.value === code)) setDistricts((current) => [...current, { value: code, label: code }]);
                set('districts', [...new Set([...(answers.districts ?? []), code])]);
                setAddDistrict('');
              }}
            >
              Add district
            </Button>
          </div>
        </div>

        <ChipGroup id="appointment" legend="Appointment needed?" options={[{ value: 'yes', label: 'Yes' }, { value: 'no', label: 'No' }]} selected={appointment} onChange={setAppointment} requirement="optional" />
        <TextField id="notes" label="Anything else advisors should know" value={notes} onChange={setNotes} requirement="optional" hint="No patient information" maxLength={500} />

        {notice !== null ? <p className={styles.notice} role="status">{notice}</p> : null}

        <div className={styles.actions}>
          <Button variant="primary" type="submit" busy={busy === 'continue'} dataEl="REG-STEP3-CONTINUE-BTN">
            Continue
          </Button>
          <Link className={styles.backLink} href={`/register/${encodeURIComponent(registrationId)}/location`}>
            Back
          </Link>
          <Button variant="neutral" busy={busy === 'save'} dataEl="REG-STEP3-SAVE-BTN" onClick={() => void save('save', fixedSite)}>
            Save draft
          </Button>
        </div>
      </form>
    </div>
  );
}
