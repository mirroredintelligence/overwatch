'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Disclose } from '@/components/admin/Disclose';
import { Button } from '@/components/ui/Button';
import { Chip } from '@/components/ui/Chip';
import { StatusTag } from '@/components/ui/StatusTag';
import { ChipGroup } from '@/components/forms/ChipGroup';
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
import { ProblemSummary } from './OrganisationForm';
import { RegisterStage } from './RegisterStage';
import form from './RegisterForm.module.css';
import styles from './ServiceSteps.module.css';

// Registration step 3, describing the service and who it is for (Reg board stage 3, RP2 board). "The service" is
// open; "Who it is for", "Criteria owner and review date" and "Area you cover" are rows that say their answer in a
// line when closed and flag what is missing, and a problem in one opens it. The service's name is set by the shift
// lead and is read-only here. Continue checks every answer here and the back end checks them again on save.

export type ServiceFormProps = { registrationId: string };

type Load = { kind: 'loading' } | { kind: 'open'; serviceName: string; fixedSite: boolean | undefined } | { kind: 'unavailable' } | { kind: 'signed-out' };
type RowName = 'who' | 'owner' | 'area';

const LOAD_FAILED = 'We could not load your registration. Try again later.';
const SIGNED_OUT = 'Please sign in again.';
const NOT_SAVED = 'Your draft is not saved. Finish the answers shown, then save again.';
const SAVED = 'Draft saved.';
const SAVED_NOTE = 'Saved a moment ago';
const DISTRICT_FORMAT = 'Enter postcode districts, for example DT4';
const DISTRICT_DEFAULTS: readonly Option[] = ['DT1', 'DT2', 'DT3', 'DT4'].map((code) => ({ value: code, label: code }));
const EXCLUSION_OPTIONS: readonly Option[] = [...EXCLUDED_NEED_OPTIONS, { value: NO_EXCLUSIONS, label: 'No exclusions' }];
/** The row that holds each field, so a problem in a closed row opens it. */
const ROW_OF: Readonly<Record<string, RowName>> = {
  needs: 'who',
  ageMin: 'who',
  ageMax: 'who',
  excludedNeeds: 'who',
  ownerRole: 'owner',
  ownerEmail: 'owner',
  reviewBy: 'owner',
  districts: 'area',
};

function errorFor(errors: FieldIssue[], field: string): string | null {
  return errors.find((issue) => issue.field === field)?.message ?? null;
}

/** Today's date in London, as the review date is compared with it. */
function londonToday(): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/London', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
}

function readableDate(iso: string): string {
  const date = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat('en-GB', { timeZone: 'UTC', day: 'numeric', month: 'short', year: 'numeric' }).format(date);
}

function labelsOf(options: readonly Option[], values: readonly string[]): string {
  return values.map((value) => options.find((option) => option.value === value)?.label ?? value).join(', ');
}

const blank = (value: string | null | undefined) => value === undefined || value === null || value.trim() === '';

/** What a closed row says: its answer, or what is missing (shape plus word). */
type Summary = { complete: boolean; hint: ReactNode };

function missing(words: string): ReactNode {
  return (
    <span className={styles.flag}>
      <span aria-hidden="true">▲ </span>
      {words}
    </span>
  );
}

function summaryOfWho(answers: ServiceAnswers): Summary {
  const needs = answers.needs ?? [];
  const exclusions = answers.noExclusions === true ? 0 : (answers.excludedNeeds ?? []).length;
  const exclusionsDone = answers.noExclusions === true || exclusions > 0;
  const agesDone = !blank(answers.ageMin) && (answers.ageMax === null || !blank(answers.ageMax));
  if (needs.length === 0 || !agesDone || !exclusionsDone) return { complete: false, hint: missing('Needs answers') };
  const age = answers.ageMax === null ? `age ${answers.ageMin?.trim()}+` : `age ${answers.ageMin?.trim()} to ${answers.ageMax?.trim()}`;
  const excluded = answers.noExclusions === true ? 'no exclusions' : exclusions === 1 ? '1 exclusion' : `${exclusions} exclusions`;
  return { complete: true, hint: <span className={styles.hint}>{`${labelsOf(NEED_OPTIONS, needs)} · ${age} · ${excluded}`}</span> };
}

function summaryOfOwner(answers: ServiceAnswers): Summary {
  const needs: string[] = [];
  if (blank(answers.ownerRole) || blank(answers.ownerEmail)) needs.push('an owner');
  if (blank(answers.reviewBy)) needs.push('a review date');
  if (needs.length > 0) return { complete: false, hint: missing(`Needs ${needs.join(' and ')}`) };
  return { complete: true, hint: <span className={styles.hint}>{`${answers.ownerRole?.trim()} · review by ${readableDate(answers.reviewBy ?? '')}`}</span> };
}

function summaryOfArea(answers: ServiceAnswers, visiting: boolean): Summary {
  const districts = answers.districts ?? [];
  if (districts.length > 0) return { complete: true, hint: <span className={styles.hint}>{districts.join(', ')}</span> };
  if (visiting) return { complete: false, hint: missing('Needs an area') };
  return { complete: false, hint: <span className={styles.hint}>Optional for a fixed site</span> };
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
  const formRef = useRef<HTMLFormElement>(null);
  const [load, setLoad] = useState<Load>({ kind: 'loading' });
  const [csrf, setCsrf] = useState<string | null>(null);
  const [answers, setAnswers] = useState<ServiceAnswers>({});
  const [errors, setErrors] = useState<FieldIssue[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [savedNote, setSavedNote] = useState<string | undefined>(undefined);
  const [busy, setBusy] = useState<'continue' | 'save' | null>(null);
  const [openRows, setOpenRows] = useState<ReadonlySet<RowName>>(new Set());
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

  const toggleRow = (row: RowName) =>
    setOpenRows((current) => {
      const next = new Set(current);
      if (next.has(row)) next.delete(row);
      else next.add(row);
      return next;
    });

  /** Shows the problems; a problem in a field that sits in a closed row opens that row. */
  function showErrors(issues: FieldIssue[]) {
    setErrors(issues);
    const rows = issues.map((issue) => ROW_OF[issue.field]).filter((row): row is RowName => row !== undefined);
    if (rows.length > 0) setOpenRows((current) => new Set([...current, ...rows]));
  }

  async function save(mode: 'continue' | 'save') {
    if (csrf === null) {
      setNotice(SIGNED_OUT);
      return;
    }
    setBusy(mode);
    setNotice(null);
    const outcome: StepOutcome = await saveStep(registrationId, 'service', bodyFrom(answers), csrf, mode === 'save');
    setBusy(null);
    if (outcome.kind === 'saved') {
      setErrors([]);
      setSavedNote(SAVED_NOTE);
      if (mode === 'continue') router.push(`/register/${encodeURIComponent(registrationId)}/reporting`);
      else setNotice(SAVED);
      return;
    }
    if (outcome.kind === 'errors') {
      showErrors(outcome.errors);
      setNotice(outcome.errors.length === 0 ? LOAD_FAILED : mode === 'save' ? NOT_SAVED : null);
      return;
    }
    setNotice(LOAD_FAILED);
  }

  const serviceName = load.kind === 'open' ? load.serviceName : undefined;
  const continueNow = () => formRef.current?.requestSubmit();
  const frame = (children: ReactNode, withContinue = false) => (
    <RegisterStage
      registrationId={registrationId}
      stage={3}
      service={serviceName}
      states={errors.length > 0 ? { 3: 'needs-attention' } : undefined}
      savedNote={savedNote}
      phoneAction={withContinue ? { primary: { label: 'Continue', busy: busy === 'continue', onClick: continueNow } } : undefined}
    >
      <div className={form.card}>
        <p className={form.step}>Step 3 of 5 · Service</p>
        <h1 className={form.heading}>Describe the service</h1>
        {children}
      </div>
    </RegisterStage>
  );

  if (load.kind === 'loading') return frame(<p role="status">Loading your registration.</p>);
  if (load.kind !== 'open') return frame(<p className={form.notice} role="status">{load.kind === 'signed-out' ? SIGNED_OUT : LOAD_FAILED}</p>);

  const fixedSite = load.fixedSite;
  const set = <K extends keyof ServiceAnswers>(key: K, value: ServiceAnswers[K]) => setAnswers((current) => ({ ...current, [key]: value }));
  const visiting = fixedSite === false;
  const rows: Record<RowName, Summary> = { who: summaryOfWho(answers), owner: summaryOfOwner(answers), area: summaryOfArea(answers, visiting) };
  const tag = (row: RowName) => (rows[row].complete ? <StatusTag variant="done">Done</StatusTag> : undefined);

  return frame(
    <form
      ref={formRef}
      className={form.form}
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        const issues = validateService(answers, { fixedSite, today: londonToday() });
        showErrors(issues);
        setNotice(null);
        if (issues.length === 0) void save('continue');
      }}
    >
      <ProblemSummary errors={errors} />

      <section className={styles.section} aria-labelledby="service-section">
        <h2 id="service-section" className={styles.sectionTitle}>The service</h2>
        <div className={styles.pair}>
          <TextField id="serviceName" label="Service name" value={load.serviceName} onChange={() => undefined} requirement="none" readOnly hint="The name advisors see, for example “UCR West”" />
          <TextField
            id="spoaPhone"
            label="Phone for the shift lead to call"
            value={answers.spoaPhone ?? ''}
            onChange={(value) => set('spoaPhone', value)}
            type="tel"
            inputMode="tel"
            hint="Staffed while you accept referrals"
            error={errorFor(errors, 'spoaPhone')}
            dataEl="REG-STEP3-PHONE-FIELD"
          />
        </div>
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
        <div className={styles.pair}>
          <TextField id="acceptingStart" label="From" value={answers.acceptingStart ?? ''} onChange={(value) => set('acceptingStart', value)} hint="HH:MM" error={errorFor(errors, 'acceptingStart')} />
          <TextField id="acceptingEnd" label="To" value={answers.acceptingEnd ?? ''} onChange={(value) => set('acceptingEnd', value)} hint="HH:MM" error={errorFor(errors, 'acceptingEnd')} />
        </div>
        <ChipGroup id="appointment" legend="Appointment needed?" options={[{ value: 'yes', label: 'Yes' }, { value: 'no', label: 'No' }]} selected={appointment} onChange={setAppointment} requirement="optional" />
        <TextField id="notes" label="Anything else advisors should know" value={notes} onChange={setNotes} requirement="optional" hint="No patient information" maxLength={500} />
      </section>

      <div className={styles.rows}>
        <Disclose open={openRows.has('who')} onToggle={() => toggleRow('who')} title="Who it is for" hint={rows.who.hint} aside={tag('who')}>
          <div className={styles.body}>
            <ChipGroup id="needs" legend="Needs you accept" options={NEED_OPTIONS} selected={answers.needs ?? []} multiple onChange={(next) => set('needs', next)} requirement="required" error={errorFor(errors, 'needs')} />
            <div className={styles.pair}>
              <TextField id="ageMin" label="Youngest age" value={answers.ageMin ?? ''} onChange={(value) => set('ageMin', value)} inputMode="numeric" hint="From 0 to 120" error={errorFor(errors, 'ageMin')} />
              <div className={form.form}>
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
          </div>
        </Disclose>

        <Disclose open={openRows.has('owner')} onToggle={() => toggleRow('owner')} title="Criteria owner and review date" hint={rows.owner.hint} aside={tag('owner')}>
          <div className={styles.body}>
            <div className={styles.pair}>
              <TextField id="ownerRole" label="Criteria owner (role)" value={answers.ownerRole ?? ''} onChange={(value) => set('ownerRole', value)} error={errorFor(errors, 'ownerRole')} />
              <TextField id="ownerEmail" label="Owner email" value={answers.ownerEmail ?? ''} onChange={(value) => set('ownerEmail', value)} type="email" autoComplete="email" error={errorFor(errors, 'ownerEmail')} />
            </div>
            <TextField id="reviewBy" label="Review criteria by" value={answers.reviewBy ?? ''} onChange={(value) => set('reviewBy', value)} type="date" hint="Advisors see a flag when this date passes" error={errorFor(errors, 'reviewBy')} />
          </div>
        </Disclose>

        <Disclose open={openRows.has('area')} onToggle={() => toggleRow('area')} title="Area you cover" hint={rows.area.hint} aside={tag('area')}>
          <div className={styles.body}>
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
            <div className={styles.add}>
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
        </Disclose>
      </div>

      {notice !== null ? <p className={form.notice} role="status">{notice}</p> : null}

      <div className={form.actions}>
        <span className={form.continue}>
          <Button variant="primary" type="submit" busy={busy === 'continue'} dataEl="REG-STEP3-CONTINUE-BTN">
            Continue
          </Button>
        </span>
        <Link className={form.backLink} href={`/register/${encodeURIComponent(registrationId)}/location`}>
          Back
        </Link>
        <Button variant="neutral" busy={busy === 'save'} dataEl="REG-STEP3-SAVE-BTN" onClick={() => void save('save')}>
          Save draft
        </Button>
      </div>
    </form>,
    true,
  );
}
