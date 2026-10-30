'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { OptionButton } from '@/components/ui/OptionButton';
import { ChipGroup } from '@/components/forms/ChipGroup';
import { ErrorSummary } from '@/components/forms/ErrorSummary';
import { TextField } from '@/components/forms/TextField';
import { saveStep, sessionCsrf, type StepOutcome } from '@/lib/register/browser';
import { normalisePostcode } from '@/lib/register/postcode';
import type { LocationAnswers } from '@/lib/register/validate';
import { validateLocation } from '@/lib/register/validate';
import type { FieldIssue } from '@/lib/register/types';
import styles from './register.module.css';

// Registration step 2, where the service is (W24, artboards RegisterFlow1 panel 4 and RegisterMobile
// panel 3). A fixed site takes its address from a postcode lookup and its hours; a visiting service
// answers the question and goes on. The postcode lookup is the BFF's, never the browser's.

export type LocationFormProps = { registrationId: string };

type Address = { id: string; label: string };

const DAYS: readonly { value: string; label: string }[] = [
  { value: '0', label: 'Mon' },
  { value: '1', label: 'Tue' },
  { value: '2', label: 'Wed' },
  { value: '3', label: 'Thu' },
  { value: '4', label: 'Fri' },
  { value: '5', label: 'Sat' },
  { value: '6', label: 'Sun' },
];
const ALL_DAY = 'all';
const ALL_DAY_OPTION = { value: ALL_DAY, label: '24 hours' };
const SITE_TYPES = [
  { value: 'ward', label: 'Ward' },
  { value: 'community-hospital', label: 'Community hospital' },
  { value: 'hub-or-base', label: 'Hub or base' },
  { value: 'clinic', label: 'Clinic' },
  { value: 'other', label: 'Other' },
];
const FIXED = [
  { value: 'yes', label: 'Yes, a building or ward' },
  { value: 'no', label: 'No, we visit patients' },
];
const NOT_FOUND = 'We could not find that postcode. Check it and try again.';
const LOOKUP_FAILED = 'We could not look up the address. Try again.';
const POSITION = 'Position found from the address. You do not need to enter coordinates.';
const SAVED = 'Draft saved.';
const NOT_SAVED = 'Your draft is not saved. Finish the answers shown, then save again.';
const SIGNED_OUT = 'Please sign in again.';

function errorFor(errors: FieldIssue[], field: string): string | null {
  return errors.find((issue) => issue.field === field)?.message ?? null;
}

/** What the form sends for its answers: the fixed-site answer alone, or the whole site. */
function bodyFrom(answers: LocationAnswers): Record<string, unknown> {
  if (answers.fixedSite !== true) return { fixedSite: answers.fixedSite === false ? false : undefined };
  const body: Record<string, unknown> = {
    fixedSite: true,
    postcode: answers.postcode,
    addressId: answers.addressId,
    address: answers.address,
    siteName: answers.siteName?.trim(),
    siteType: answers.siteType,
    hours: {
      days: [...(answers.days ?? [])].sort((a, b) => a - b),
      allDay: answers.allDay === true,
      ...(answers.allDay === true ? {} : { opens: answers.opens, closes: answers.closes }),
    },
  };
  if (answers.siteOdsCode?.trim()) body.siteOdsCode = answers.siteOdsCode.trim();
  for (const key of Object.keys(body)) if (body[key] === undefined) delete body[key];
  return body;
}

export function LocationForm({ registrationId }: LocationFormProps) {
  const router = useRouter();
  const [answers, setAnswers] = useState<LocationAnswers>({});
  const [addresses, setAddresses] = useState<Address[] | null>(null);
  const [lookupError, setLookupError] = useState<string | null>(null);
  const [errors, setErrors] = useState<FieldIssue[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<'continue' | 'save' | 'find' | null>(null);

  const base = `/register/${encodeURIComponent(registrationId)}`;
  const set = <K extends keyof LocationAnswers>(key: K, value: LocationAnswers[K]) => {
    setAnswers((current) => ({ ...current, [key]: value }));
  };

  async function findAddress() {
    const postcode = normalisePostcode(answers.postcode ?? '');
    if (postcode === null) {
      setLookupError(answers.postcode?.trim() ? 'Enter a full postcode' : 'Enter a postcode');
      return;
    }
    setBusy('find');
    setLookupError(null);
    let response: Response;
    try {
      response = await fetch(`/api/bff/addresses?postcode=${encodeURIComponent(postcode)}`, { cache: 'no-store', credentials: 'same-origin' });
    } catch {
      setBusy(null);
      setNotice(LOOKUP_FAILED);
      return;
    }
    setBusy(null);
    if (response.status === 401) {
      setNotice(SIGNED_OUT);
      return;
    }
    if (!response.ok) {
      setNotice(LOOKUP_FAILED);
      return;
    }
    const found = (await response.json().catch(() => [])) as unknown;
    const list = Array.isArray(found)
      ? found.filter((item): item is Address => typeof item?.id === 'string' && typeof item?.label === 'string')
      : [];
    setAddresses(list);
    if (list.length === 0) setLookupError(NOT_FOUND);
    setAnswers((current) => ({ ...current, postcode, addressId: undefined, address: undefined }));
  }

  async function save(mode: 'continue' | 'save') {
    const csrf = await sessionCsrf();
    if (csrf === null) {
      setNotice(SIGNED_OUT);
      return;
    }
    setBusy(mode);
    setNotice(null);
    const outcome: StepOutcome = await saveStep(registrationId, 'location', bodyFrom(answers), csrf);
    setBusy(null);
    if (outcome.kind === 'saved') {
      setErrors([]);
      if (mode === 'continue') router.push(`${base}/service`);
      else setNotice(SAVED);
      return;
    }
    if (outcome.kind === 'errors') {
      setErrors(outcome.errors);
      setNotice(outcome.errors.length === 0 ? LOOKUP_FAILED : mode === 'save' ? NOT_SAVED : null);
      return;
    }
    setNotice(LOOKUP_FAILED);
  }

  const fixed = answers.fixedSite;
  const allDay = answers.allDay === true;
  const dayValues = allDay ? [ALL_DAY] : (answers.days ?? []).map(String);

  return (
    <div className={styles.stack}>
      <p className={styles.product}>DIUCS capacity</p>
      <p className={styles.note}>Step 2 of 5 · Location</p>
      <h1 className={styles.heading}>Where is the service?</h1>

      <form
        className={styles.stack}
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          const issues = validateLocation(answers);
          setErrors(issues);
          setNotice(null);
          if (issues.length === 0) void save('continue');
        }}
      >
        <ErrorSummary errors={errors} />
        <ChipGroup
          id="fixedSite"
          legend="Do you have a fixed site?"
          options={FIXED}
          selected={fixed === undefined ? [] : [fixed ? 'yes' : 'no']}
          onChange={(next) => {
            const pick = next[0];
            set('fixedSite', pick === undefined ? undefined : pick === 'yes');
          }}
          requirement="required"
          hint="Choose No for services that visit patients, such as community response or virtual wards. You will add the area you cover in step 3."
          error={errorFor(errors, 'fixedSite')}
          dataEl="REG-STEP2-FIXED"
        />

        {fixed === true ? (
          <>
            <div className={styles.stack}>
              <TextField
                id="postcode"
                label="Postcode"
                value={answers.postcode ?? ''}
                onChange={(value) => set('postcode', value)}
                autoComplete="postal-code"
                error={lookupError ?? errorFor(errors, 'postcode')}
                dataEl="REG-STEP2-POSTCODE"
              />
              <Button variant="secondary" busy={busy === 'find'} dataEl="REG-STEP2-FIND-BTN" onClick={() => void findAddress()}>
                Find address
              </Button>
            </div>

            {addresses !== null && addresses.length > 0 ? (
              <fieldset id="address" tabIndex={-1} className={styles.stack} aria-describedby={errorFor(errors, 'address') ? 'address-error' : undefined}>
                <legend className={styles.legend}>Choose the address</legend>
                {addresses.map((address) => (
                  <OptionButton
                    key={address.id}
                    selected={answers.addressId === address.id}
                    onSelect={() => setAnswers((current) => ({ ...current, addressId: address.id, address: address.label }))}
                    dataEl="REG-STEP2-ADDRESS"
                  >
                    {address.label}
                  </OptionButton>
                ))}
                {errorFor(errors, 'address') ? (
                  <p id="address-error" className={styles.error}>{errorFor(errors, 'address')}</p>
                ) : null}
              </fieldset>
            ) : null}

            {answers.addressId !== undefined ? <p className={styles.notice}>{POSITION}</p> : null}

            <TextField
              id="siteName"
              label="Site name"
              value={answers.siteName ?? ''}
              onChange={(value) => set('siteName', value)}
              error={errorFor(errors, 'siteName')}
            />
            <ChipGroup
              id="siteType"
              legend="Site type"
              options={SITE_TYPES}
              selected={answers.siteType === undefined ? [] : [answers.siteType]}
              onChange={(next) => set('siteType', next[0])}
              requirement="required"
              error={errorFor(errors, 'siteType')}
              dataEl="REG-STEP2-SITE-TYPE"
            />
            <ChipGroup
              id="opening"
              legend="Opening hours"
              options={[...DAYS, ALL_DAY_OPTION]}
              selected={dayValues}
              multiple
              requirement="required"
              onChange={(next) => {
                const added = next.filter((value) => !dayValues.includes(value));
                if (added.includes(ALL_DAY)) {
                  setAnswers((current) => ({ ...current, allDay: true, days: [] }));
                  return;
                }
                const days = next.filter((value) => value !== ALL_DAY).map(Number);
                setAnswers((current) => ({ ...current, allDay: false, days }));
              }}
              error={errorFor(errors, 'opening')}
              dataEl="REG-STEP2-DAY"
            />
            {!allDay ? (
              <div className={styles.stack}>
                <TextField
                  id="opens"
                  label="Opens"
                  value={answers.opens ?? ''}
                  onChange={(value) => set('opens', value)}
                  hint="HH:MM"
                  error={errorFor(errors, 'opens')}
                />
                <TextField
                  id="closes"
                  label="Closes"
                  value={answers.closes ?? ''}
                  onChange={(value) => set('closes', value)}
                  hint="HH:MM"
                  error={errorFor(errors, 'closes')}
                />
              </div>
            ) : null}
            <TextField
              id="siteOdsCode"
              label="Site ODS code"
              value={answers.siteOdsCode ?? ''}
              onChange={(value) => set('siteOdsCode', value)}
              requirement="optional"
            />
          </>
        ) : null}

        {notice !== null ? <p className={styles.notice} role="status">{notice}</p> : null}

        <div className={styles.actions}>
          <Button variant="primary" type="submit" busy={busy === 'continue'} dataEl="REG-STEP2-CONTINUE-BTN">
            Continue
          </Button>
          <Link className={styles.backLink} href={`${base}/organisation`}>
            Back
          </Link>
          <Button variant="neutral" busy={busy === 'save'} dataEl="REG-STEP2-SAVE-BTN" onClick={() => void save('save')}>
            Save draft
          </Button>
        </div>
      </form>
    </div>
  );
}
