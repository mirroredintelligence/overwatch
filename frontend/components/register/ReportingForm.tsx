'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { ChipGroup } from '@/components/forms/ChipGroup';
import { ErrorSummary } from '@/components/forms/ErrorSummary';
import { TextField } from '@/components/forms/TextField';
import { saveStep, sessionCsrf, type StepOutcome } from '@/lib/register/browser';
import { CADENCE_OPTIONS, CHANNEL_OPTIONS, COUNT_OPTIONS } from '@/lib/register/options';
import { measureCodeOf, validateApi, validateReporting, type ApiAnswers, type ReportingAnswers } from '@/lib/register/reporting';
import type { FieldIssue } from '@/lib/register/types';
import styles from './register.module.css';

// Registration step 4, how the service reports capacity (W26, artboard RegisterFlow2 panel 7). The
// reporting answers are saved, then the API answer; both must pass before the review opens. What is
// on the screen and not yet in the back end (bed types, cover number) is said in the known issues.

export type ReportingFormProps = { registrationId: string };

/** Everything the form holds. The API answer is `api` ("yes" or "no") and its four details. */
type Answers = ReportingAnswers & ApiAnswers & { api?: string; coverNumber?: string };

const BED_TYPES = ['Women only', 'Men only', 'Side room', 'Rehab', 'Palliative'];
const SIGNED_OUT = 'Please sign in again.';
const NOT_SAVED = 'Your draft is not saved. Finish the answers shown, then save again.';
const SAVED = 'Draft saved.';
const LOAD_FAILED = 'We could not save that. Try again.';
const API_OPTIONS = [
  { value: 'no', label: 'No' },
  { value: 'yes', label: 'Yes' },
];

function errorFor(errors: FieldIssue[], field: string): string | null {
  return errors.find((issue) => issue.field === field)?.message ?? null;
}

export function ReportingForm({ registrationId }: ReportingFormProps) {
  const router = useRouter();
  const [answers, setAnswers] = useState<Answers>({});
  const [errors, setErrors] = useState<FieldIssue[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<'continue' | 'save' | null>(null);
  const [beds, setBeds] = useState<string[]>([]);
  const set = <K extends keyof Answers>(key: K, value: Answers[K]) => setAnswers((current) => ({ ...current, [key]: value }));

  const api = answers.api === 'yes';
  const channel = answers.channel;

  async function save(mode: 'continue' | 'save') {
    const csrf = await sessionCsrf();
    if (csrf === null) {
      setNotice(SIGNED_OUT);
      return;
    }
    const measure = answers.counts === undefined ? undefined : measureCodeOf(answers.counts);
    const reporting: Record<string, unknown> = {
      measure,
      usualRange: [Number(answers.usualLow), Number(answers.usualHigh)],
      cadence: answers.cadence,
      channel: answers.channel,
      holderName: answers.holderName?.trim(),
    };
    if (channel === 'email') reporting.contactEmail = answers.contactEmail?.trim();
    else reporting.contactMobile = answers.contactMobile?.replace(/[\s-]/g, '');
    const apiBody: Record<string, unknown> = api
      ? { wanted: true, name: answers.name?.trim(), address: answers.address?.trim(), connection: answers.connection?.trim(), dataType: answers.dataType?.trim() }
      : { wanted: false };

    setBusy(mode);
    setNotice(null);
    const first: StepOutcome = await saveStep(registrationId, 'reporting', reporting, csrf);
    const second: StepOutcome = first.kind === 'saved' ? await saveStep(registrationId, 'api', apiBody, csrf) : first;
    setBusy(null);
    if (second.kind === 'saved') {
      setErrors([]);
      if (mode === 'continue') router.push(`/register/${encodeURIComponent(registrationId)}/review`);
      else setNotice(SAVED);
      return;
    }
    if (second.kind === 'errors') {
      setErrors(second.errors);
      setNotice(second.errors.length === 0 ? LOAD_FAILED : mode === 'save' ? NOT_SAVED : null);
      return;
    }
    setNotice(LOAD_FAILED);
  }

  return (
    <div className={styles.stack}>
      <p className={styles.product}>DIUCS capacity</p>
      <p className={styles.note}>Step 4 of 5 · Capacity reporting</p>
      <h1 className={styles.heading}>How will you report capacity?</h1>

      <form
        className={styles.stack}
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          const issues = [...validateReporting(answers), ...(api ? validateApi({ wanted: true, ...answers }) : [])];
          setErrors(issues);
          setNotice(null);
          if (issues.length === 0) void save('continue');
        }}
      >
        <ErrorSummary errors={errors} />
        <ChipGroup
          id="counts"
          legend="What do you count?"
          options={COUNT_OPTIONS}
          selected={answers.counts === undefined ? [] : [answers.counts]}
          onChange={(next) => set('counts', next[0])}
          requirement="required"
          error={errorFor(errors, 'counts')}
          dataEl="REG-STEP4-COUNT"
        />
        <TextField id="usualLow" label="Lowest usual number" value={answers.usualLow ?? ''} onChange={(value) => set('usualLow', value)} inputMode="numeric" error={errorFor(errors, 'usualLow')} />
        <TextField id="usualHigh" label="Highest usual number" value={answers.usualHigh ?? ''} onChange={(value) => set('usualHigh', value)} inputMode="numeric" error={errorFor(errors, 'usualHigh')} />
        <ChipGroup
          id="cadence"
          legend="How often do you report?"
          options={CADENCE_OPTIONS}
          selected={answers.cadence === undefined ? [] : [answers.cadence]}
          onChange={(next) => set('cadence', next[0])}
          requirement="required"
          error={errorFor(errors, 'cadence')}
        />
        <ChipGroup
          id="channel"
          legend="How will you report?"
          options={CHANNEL_OPTIONS}
          selected={answers.channel === undefined ? [] : [answers.channel]}
          onChange={(next) => set('channel', next[0])}
          requirement="required"
          hint="App notification needs the app on your home screen. Services that can do none of these are outside the pilot."
          error={errorFor(errors, 'channel')}
        />
        {channel === 'text' || channel === 'push' ? (
          <TextField
            id="contactMobile"
            label="Mobile number"
            value={answers.contactMobile ?? ''}
            onChange={(value) => set('contactMobile', value)}
            type="tel"
            inputMode="tel"
            hint="A ward or team phone is best. It stays with the post, not the person."
            error={errorFor(errors, 'contactMobile')}
          />
        ) : null}
        {channel === 'email' ? (
          <TextField id="contactEmail" label="Email address" value={answers.contactEmail ?? ''} onChange={(value) => set('contactEmail', value)} type="email" error={errorFor(errors, 'contactEmail')} />
        ) : null}
        <TextField id="holderName" label="Who holds this phone" value={answers.holderName ?? ''} onChange={(value) => set('holderName', value)} error={errorFor(errors, 'holderName')} />
        <TextField id="coverNumber" label="Cover number" value={answers.coverNumber ?? ''} onChange={(value) => set('coverNumber', value)} requirement="optional" type="tel" />
        <ChipGroup
          id="bedTypes"
          legend="Types of bed or slot you report"
          options={BED_TYPES.map((label) => ({ value: label, label }))}
          selected={beds}
          multiple
          requirement="optional"
          onChange={setBeds}
        />
        <ChipGroup
          id="api"
          legend="Does your system have an API?"
          options={API_OPTIONS}
          selected={answers.api === undefined ? [] : [answers.api]}
          onChange={(next) => set('api', next[0])}
          requirement="optional"
          hint="Not used in the pilot. If you answer Yes, we ask for the details below and keep them for later."
        />
        {api ? (
          <div className={styles.stack}>
            <TextField id="name" label="API name" value={answers.name ?? ''} onChange={(value) => set('name', value)} error={errorFor(errors, 'name')} />
            <TextField id="address" label="API address" value={answers.address ?? ''} onChange={(value) => set('address', value)} type="url" inputMode="url" error={errorFor(errors, 'address')} />
            <TextField id="connection" label="Connection type" value={answers.connection ?? ''} onChange={(value) => set('connection', value)} error={errorFor(errors, 'connection')} />
            <TextField id="dataType" label="Type of data" value={answers.dataType ?? ''} onChange={(value) => set('dataType', value)} error={errorFor(errors, 'dataType')} />
          </div>
        ) : null}

        {notice !== null ? <p className={styles.notice} role="status">{notice}</p> : null}

        <div className={styles.actions}>
          <Button variant="primary" type="submit" busy={busy === 'continue'} dataEl="REG-STEP4-CONTINUE-BTN">
            Continue
          </Button>
          <Link className={styles.backLink} href={`/register/${encodeURIComponent(registrationId)}/service`}>
            Back
          </Link>
          <Button variant="neutral" busy={busy === 'save'} dataEl="REG-STEP4-SAVE-BTN" onClick={() => void save('save')}>
            Save draft
          </Button>
        </div>
      </form>
    </div>
  );
}
