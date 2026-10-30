'use client';

import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { ChipGroup } from '@/components/forms/ChipGroup';
import { ErrorSummary } from '@/components/forms/ErrorSummary';
import { TextField } from '@/components/forms/TextField';
import { loadRegistration, saveStep, sessionCsrf, type StepOutcome } from '@/lib/register/browser';
import { ORGANISATION_TYPES } from '@/lib/register/options';
import { validateOrganisation, type OrganisationAnswers } from '@/lib/register/validate';
import type { FieldIssue, Invitation } from '@/lib/register/types';
import styles from './register.module.css';

// Registration step 1, the organisation (W54, artboard RegisterFlow1 panel 3). What the invitation
// fixes is shown as text and cannot be changed. "Continue" checks the answers, saves them and goes on
// to step 2; "Save draft" saves what is there. The back end's refusals come back as the same errors.

export type OrganisationFormProps = { registrationId: string };

type Load = { kind: 'loading' } | { kind: 'open'; invitation: Invitation } | { kind: 'unavailable' } | { kind: 'signed-out' };

const LOAD_FAILED = 'We could not load your registration. Try again later.';
const SIGNED_OUT = 'Please sign in again.';
const NOT_SAVED = 'Your draft is not saved. Finish the answers shown, then save again.';
const SAVED = 'Draft saved.';

function errorFor(errors: FieldIssue[], field: string): string | null {
  return errors.find((issue) => issue.field === field)?.message ?? null;
}

export function OrganisationForm({ registrationId }: OrganisationFormProps) {
  const router = useRouter();
  const [load, setLoad] = useState<Load>({ kind: 'loading' });
  const [csrf, setCsrf] = useState<string | null>(null);
  const [answers, setAnswers] = useState<OrganisationAnswers>({});
  const [errors, setErrors] = useState<FieldIssue[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<'continue' | 'save' | null>(null);
  const [notMine, setNotMine] = useState(false);

  useEffect(() => {
    let alive = true;
    void (async () => {
      const [outcome, token] = await Promise.all([loadRegistration(registrationId), sessionCsrf()]);
      if (!alive) return;
      setCsrf(token);
      if (outcome.kind === 'open') {
        setLoad({ kind: 'open', invitation: outcome.view.invitation });
        setAnswers({ ...(outcome.view.steps.organisation as OrganisationAnswers | undefined) });
      } else {
        setLoad({ kind: outcome.kind });
      }
    })();
    return () => {
      alive = false;
    };
  }, [registrationId]);

  async function save(mode: 'continue' | 'save') {
    if (csrf === null) {
      setNotice(SIGNED_OUT);
      return;
    }
    const body: Record<string, unknown> = {};
    for (const key of ['orgType', 'contactName', 'contactRole', 'contact'] as const) {
      const value = answers[key]?.trim();
      if (value !== undefined && value !== '') body[key] = value;
    }
    setBusy(mode);
    setNotice(null);
    const outcome: StepOutcome = await saveStep(registrationId, 'organisation', body, csrf);
    setBusy(null);
    if (outcome.kind === 'saved') {
      setErrors([]);
      if (mode === 'continue') router.push(`/register/${encodeURIComponent(registrationId)}/location`);
      else setNotice(SAVED);
      return;
    }
    if (outcome.kind === 'errors') {
      setErrors(outcome.errors);
      setNotice(mode === 'save' ? NOT_SAVED : null);
      if (outcome.errors.length === 0) setNotice(LOAD_FAILED);
      return;
    }
    setNotice(LOAD_FAILED);
  }

  const header = (
    <>
      <p className={styles.product}>DIUCS capacity</p>
      <p className={styles.note}>Step 1 of 5 · Organisation</p>
      <h1 className={styles.heading}>Your organisation</h1>
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

  const { invitation } = load;
  const set = (key: keyof OrganisationAnswers) => (value: string) => {
    setAnswers((current) => ({ ...current, [key]: value }));
  };

  return (
    <div className={styles.stack}>
      {header}
      <dl className={styles.locked}>
        <div>
          <dt>Service</dt>
          <dd>{invitation.serviceName}</dd>
        </div>
        <div>
          <dt>Organisation</dt>
          <dd>{invitation.organisationName}</dd>
        </div>
        <div>
          <dt>ODS code</dt>
          <dd>{invitation.odsCode}</dd>
        </div>
      </dl>
      <p className={styles.note}>From your invitation. It cannot be changed.</p>

      <form
        className={styles.stack}
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          const issues = validateOrganisation(answers);
          setErrors(issues);
          setNotice(null);
          if (issues.length === 0) void save('continue');
        }}
      >
        <ErrorSummary errors={errors} />
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
        <TextField
          id="partOf"
          label="Part of a larger organisation"
          value={answers.partOf ?? ''}
          onChange={set('partOf')}
          requirement="optional"
        />
        <TextField
          id="contactName"
          label="Your name"
          value={answers.contactName ?? ''}
          onChange={set('contactName')}
          autoComplete="name"
          error={errorFor(errors, 'contactName')}
        />
        <TextField
          id="contactRole"
          label="Your role"
          value={answers.contactRole ?? ''}
          onChange={set('contactRole')}
          error={errorFor(errors, 'contactRole')}
        />
        <TextField
          id="contact"
          label="Contact email or phone"
          value={answers.contact ?? ''}
          onChange={set('contact')}
          hint="For the SPOA to reach your organisation about this registration"
          error={errorFor(errors, 'contact')}
          autoComplete="email"
        />

        {notice !== null ? <p className={styles.notice} role="status">{notice}</p> : null}

        <div className={styles.actions}>
          <Button variant="primary" type="submit" busy={busy === 'continue'} dataEl="REG-STEP1-CONTINUE-BTN">
            Continue
          </Button>
          <Link className={styles.backLink} href={`/register/${encodeURIComponent(registrationId)}/start`}>
            Back
          </Link>
          <Button
            variant="neutral"
            busy={busy === 'save'}
            dataEl="REG-STEP1-SAVE-BTN"
            onClick={() => void save('save')}
          >
            Save draft
          </Button>
        </div>

        <div className={styles.stack}>
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
              Not your service, or the details are wrong? Tell the SPOA shift lead. Do not carry on.
            </p>
          ) : null}
        </div>
      </form>
    </div>
  );
}
