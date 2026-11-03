'use client';

import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import { Disclose } from '@/components/admin/Disclose';
import { Button } from '@/components/ui/Button';
import { Loading, SkeletonRows } from '@/components/ui/Skeleton';
import { ChipGroup } from '@/components/forms/ChipGroup';
import { TextField } from '@/components/forms/TextField';
import { loadRegistration, saveStep, sessionCsrf, type StepOutcome } from '@/lib/register/browser';
import { ORGANISATION_TYPES } from '@/lib/register/options';
import { validateOrganisation, type OrganisationAnswers } from '@/lib/register/validate';
import type { FieldIssue } from '@/lib/register/types';
import { RegisterStage } from './RegisterStage';
import styles from './RegisterForm.module.css';

// Registration step 1, the organisation (Reg board stage 1, RP2 board for the errors). The form sits in the
// register frame. The service is set by the shift lead and shown in the top bar. The organisation's name and ODS
// code are typed here (DEC-910); the reviewer's checks confirm them. The role and the parent organisation are under
// "More about your organisation". "Continue" checks the answers, saves them and goes on to step 2; "Save draft"
// saves what is there. Fields the back end cannot keep are on screen but never sent (DEC-906).

export type OrganisationFormProps = { registrationId: string };

type Load = { kind: 'loading' } | { kind: 'open'; serviceName: string } | { kind: 'unavailable' } | { kind: 'signed-out' };

const LOAD_FAILED = 'We could not load your registration. Try again later.';
const SIGNED_OUT = 'Please sign in again.';
const NOT_SAVED = 'Your draft is not saved. Finish the answers shown, then save again.';
const SAVED = 'Draft saved.';
const SAVED_NOTE = 'Saved a moment ago';
/** The answers under "More about your organisation": an error on one of them opens the row. */
const MORE_FIELDS: readonly string[] = ['contactRole', 'partOf'];

function errorFor(errors: FieldIssue[], field: string): string | null {
  return errors.find((issue) => issue.field === field)?.message ?? null;
}

/**
 * The polite summary at the top of a step with problems (RP2 board): "3 problems to fix", each a link to its
 * field. It takes focus when it appears, so a screen reader reads what is wrong first. Shared by the first two steps.
 */
export function ProblemSummary({ errors }: { errors: FieldIssue[] }) {
  const region = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (errors.length > 0) region.current?.focus();
  }, [errors]);

  if (errors.length === 0) return null;
  const heading = errors.length === 1 ? '1 problem to fix' : `${errors.length} problems to fix`;

  return (
    <div ref={region} role="alert" tabIndex={-1} className={styles.summary} data-el="REG-ERROR-SUMMARY">
      <h2 className={styles.summaryHeading}>
        <span aria-hidden="true">▲ </span>
        {heading}
      </h2>
      <ul className={styles.summaryList}>
        {errors.map((error, index) => (
          <li key={`${error.field}-${index}`}>
            <a
              href={`#${error.field}`}
              onClick={(event) => {
                const target = document.getElementById(error.field);
                if (target === null) return;
                event.preventDefault();
                target.focus();
              }}
            >
              {error.message}
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function OrganisationForm({ registrationId }: OrganisationFormProps) {
  const router = useRouter();
  const form = useRef<HTMLFormElement>(null);
  const [load, setLoad] = useState<Load>({ kind: 'loading' });
  const [csrf, setCsrf] = useState<string | null>(null);
  const [answers, setAnswers] = useState<OrganisationAnswers>({});
  const [errors, setErrors] = useState<FieldIssue[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [savedNote, setSavedNote] = useState<string | undefined>(undefined);
  const [busy, setBusy] = useState<'continue' | 'save' | null>(null);
  const [notMine, setNotMine] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    void (async () => {
      const [outcome, token] = await Promise.all([loadRegistration(registrationId), sessionCsrf()]);
      if (!alive) return;
      setCsrf(token);
      if (outcome.kind === 'open') {
        setLoad({ kind: 'open', serviceName: outcome.view.serviceName });
        setAnswers({ ...(outcome.view.steps.organisation as OrganisationAnswers | undefined) });
      } else {
        setLoad({ kind: outcome.kind });
      }
    })();
    return () => {
      alive = false;
    };
  }, [registrationId]);

  /** Shows the problems; a problem in a field that sits under "More about your organisation" opens that row. */
  function showErrors(issues: FieldIssue[]) {
    setErrors(issues);
    if (issues.some((issue) => MORE_FIELDS.includes(issue.field))) setMoreOpen(true);
  }

  async function save(mode: 'continue' | 'save') {
    if (csrf === null) {
      setNotice(SIGNED_OUT);
      return;
    }
    const body: Record<string, unknown> = {};
    // The contact role and the part-of answer are on screen only: the back end cannot keep them (DEC-906).
    for (const key of ['name', 'odsCode', 'orgType', 'contactName', 'contact'] as const) {
      const value = answers[key]?.trim();
      if (value !== undefined && value !== '') body[key] = value;
    }
    setBusy(mode);
    setNotice(null);
    const outcome: StepOutcome = await saveStep(registrationId, 'organisation', body, csrf, mode === 'save');
    setBusy(null);
    if (outcome.kind === 'saved') {
      setErrors([]);
      setSavedNote(SAVED_NOTE);
      if (mode === 'continue') router.push(`/register/${encodeURIComponent(registrationId)}/location`);
      else setNotice(SAVED);
      return;
    }
    if (outcome.kind === 'errors') {
      showErrors(outcome.errors);
      setNotice(mode === 'save' ? NOT_SAVED : null);
      if (outcome.errors.length === 0) setNotice(LOAD_FAILED);
      return;
    }
    setNotice(LOAD_FAILED);
  }

  const header = (
    <>
      <p className={styles.step}>Step 1 of 5 · Organisation</p>
      <h1 className={styles.heading}>Tell us about your organisation</h1>
    </>
  );

  if (load.kind !== 'open') {
    return (
      <RegisterStage registrationId={registrationId} stage={1}>
        <div className={styles.card}>
          {header}
          {load.kind === 'loading' ? (
            <div className={styles.loading}>
              <Loading label="Loading your registration.">
                <SkeletonRows count={3} />
              </Loading>
            </div>
          ) : (
            <p className={styles.notice} role="status">
              {load.kind === 'signed-out' ? SIGNED_OUT : LOAD_FAILED}
            </p>
          )}
        </div>
      </RegisterStage>
    );
  }

  const set = (key: keyof OrganisationAnswers) => (value: string) => {
    setAnswers((current) => ({ ...current, [key]: value }));
  };
  const submitting = busy === 'continue';

  return (
    <RegisterStage
      registrationId={registrationId}
      stage={1}
      service={load.serviceName}
      savedNote={savedNote}
      phoneAction={{
        primary: { label: 'Continue', busy: submitting, onClick: () => form.current?.requestSubmit() },
      }}
    >
      <div className={styles.card}>
        {header}
        <form
          ref={form}
          className={styles.form}
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            const issues = validateOrganisation(answers);
            showErrors(issues);
            setNotice(null);
            if (issues.length === 0) void save('continue');
          }}
        >
          <ProblemSummary errors={errors} />
          <div className={styles.pair}>
            <TextField
              id="name"
              label="Organisation name"
              value={answers.name ?? ''}
              onChange={set('name')}
              autoComplete="organization"
              error={errorFor(errors, 'name')}
            />
            <TextField
              id="odsCode"
              label="ODS code"
              value={answers.odsCode ?? ''}
              onChange={set('odsCode')}
              hint="Your organisation's code in the NHS Organisation Data Service. Your shift lead checks it against the NHS register."
              error={errorFor(errors, 'odsCode')}
            />
          </div>
          <ChipGroup
            id="orgType"
            legend="Organisation type"
            options={ORGANISATION_TYPES}
            selected={answers.orgType === undefined ? [] : [answers.orgType]}
            onChange={(next) => setAnswers((current) => ({ ...current, orgType: next[0] }))}
            requirement="required"
            error={errorFor(errors, 'orgType')}
            dataEl="REG-STEP1-TYPE"
          />
          <div className={styles.pair}>
            <TextField
              id="contactName"
              label="Contact name"
              value={answers.contactName ?? ''}
              onChange={set('contactName')}
              autoComplete="name"
              error={errorFor(errors, 'contactName')}
            />
            <TextField
              id="contact"
              label="Contact email or phone"
              value={answers.contact ?? ''}
              onChange={set('contact')}
              hint="For the coordination team to reach your organisation about this registration"
              error={errorFor(errors, 'contact')}
              autoComplete="email"
            />
          </div>
          <Disclose
            open={moreOpen}
            onToggle={() => setMoreOpen((open) => !open)}
            title="More about your organisation"
            hint={<span className={styles.moreHint}>Your role, parent organisation</span>}
          >
            <div className={styles.more}>
              <TextField
                id="contactRole"
                label="Your role"
                value={answers.contactRole ?? ''}
                onChange={set('contactRole')}
                error={errorFor(errors, 'contactRole')}
              />
              <TextField
                id="partOf"
                label="Part of a larger organisation"
                value={answers.partOf ?? ''}
                onChange={set('partOf')}
                requirement="optional"
              />
            </div>
          </Disclose>

          {notice !== null ? <p className={styles.notice} role="status">{notice}</p> : null}

          <div className={styles.actions}>
            <span className={styles.continue}>
              <Button variant="primary" type="submit" busy={submitting} dataEl="REG-STEP1-CONTINUE-BTN">
                Continue
              </Button>
            </span>
            <Link className={styles.backLink} href={`/register/${encodeURIComponent(registrationId)}/start`}>
              Back
            </Link>
            <Button variant="neutral" busy={busy === 'save'} dataEl="REG-STEP1-SAVE-BTN" onClick={() => void save('save')}>
              Save draft
            </Button>
          </div>

          <div className={styles.form}>
            <button
              type="button"
              className={styles.linkButton}
              aria-expanded={notMine}
              data-el="REG-STEP1-NOTMINE-LINK"
              onClick={() => setNotMine((open) => !open)}
            >
              This is not my service
            </button>
            {notMine ? (
              <p className={styles.notice} data-el="REG-STEP1-NOTMINE-TEXT">
                Not your service, or the details are wrong? Tell the shift lead. Do not carry on.
              </p>
            ) : null}
          </div>
        </form>
      </div>
    </RegisterStage>
  );
}
