'use client';

import { useRouter } from 'next/navigation';
import { type FormEvent, useEffect, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Chip } from '@/components/ui/Chip';
import {
  AGE_BANDS,
  type AgeCode,
  type CaseInput,
  type CaseView,
  labelOf,
  NEEDS,
  type NeedCode,
  REFERRERS,
  type ReferrerCode,
  URGENCIES,
  type UrgencyCode,
} from '@/lib/advisor/codes';
import { bffFetch } from '@/lib/advisor/browser';
import { normalisePostcode } from '@/lib/advisor/postcode';
import { CallBar } from './CallBar';
import styles from './NeedsForm.module.css';

// The needs form (W11): who is calling, age, postcode, needs and how soon. Nothing is typed except
// the postcode. The form is not editable until the case has been read, so a save never overwrites
// a case the page has not seen. A save sends the ETag it read as If-Match (W11).

const POSTCODE_ERROR = 'Enter a full postcode, for example DT4 8XX';
const POSTCODE_ERROR_ID = 'needs-postcode-error';
const POSTCODE_ID = 'needs-postcode';

type Draft = {
  referrerType: ReferrerCode | null;
  ageBand: AgeCode | null;
  postcode: string;
  needs: NeedCode[];
  urgency: UrgencyCode | null;
};

type Load = { kind: 'loading' } | { kind: 'ready'; view: CaseView } | { kind: 'failed' };

const EMPTY: Draft = { referrerType: null, ageBand: null, postcode: '', needs: [], urgency: null };

function draftFrom(view: CaseView): Draft {
  return {
    referrerType: view.referrerType,
    ageBand: view.ageBand,
    postcode: view.postcode ?? '',
    needs: view.needs,
    urgency: view.urgency,
  };
}

/** The coded save, or null while any part is still unset or the postcode is not full. */
function inputFrom(draft: Draft, postcode: string | null): CaseInput | null {
  if (draft.referrerType === null || draft.ageBand === null || draft.urgency === null) return null;
  if (postcode === null || draft.needs.length === 0) return null;
  return {
    referrerType: draft.referrerType,
    ageBand: draft.ageBand,
    postcode,
    needs: draft.needs,
    urgency: draft.urgency,
    scores: [],
  };
}

export function NeedsForm({ caseId, openedAt }: { caseId: string; openedAt: string }) {
  const router = useRouter();
  const [load, setLoad] = useState<Load>({ kind: 'loading' });
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [showMore, setShowMore] = useState(false);
  const [postcodeError, setPostcodeError] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<'conflict' | 'failed' | null>(null);

  useEffect(() => {
    let live = true;
    bffFetch<CaseView>(`/api/bff/cases/${encodeURIComponent(caseId)}`).then((reply) => {
      if (!live) return;
      if (reply.ok) {
        setLoad({ kind: 'ready', view: reply.body });
        setDraft(draftFrom(reply.body));
      } else {
        setLoad({ kind: 'failed' });
      }
    });
    return () => {
      live = false;
    };
  }, [caseId]);

  const postcode = normalisePostcode(draft.postcode);
  const input = inputFrom(draft, postcode);
  const canContinue = load.kind === 'ready' && input !== null && !saving;

  function onPostcodeBlur() {
    const normal = normalisePostcode(draft.postcode);
    if (normal !== null) {
      setDraft((current) => ({ ...current, postcode: normal }));
      setPostcodeError(false);
      return;
    }
    // An empty field is not an error until something is typed; a wrong one says what a right one looks like.
    setPostcodeError(draft.postcode.trim() !== '');
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (load.kind !== 'ready') return;
    if (input === null) {
      setPostcodeError(normalisePostcode(draft.postcode) === null && draft.postcode.trim() !== '');
      return;
    }
    setSaving(true);
    setMessage(null);
    const reply = await bffFetch<CaseView>(`/api/bff/cases/${encodeURIComponent(caseId)}`, {
      method: 'PUT',
      body: input,
      ifMatch: load.view.etag ?? undefined,
    });
    if (reply.ok) {
      router.push(`/advisor/case/${encodeURIComponent(caseId)}/options`);
      return;
    }
    setSaving(false);
    setMessage(reply.code === 'conflict' ? 'conflict' : 'failed');
  }

  const setReferrer = (code: ReferrerCode) => setDraft((current) => ({ ...current, referrerType: code }));
  const setAge = (code: AgeCode) => setDraft((current) => ({ ...current, ageBand: code }));
  const setUrgency = (code: UrgencyCode) => setDraft((current) => ({ ...current, urgency: code }));
  const toggleNeed = (code: NeedCode, on: boolean) =>
    setDraft((current) => ({
      ...current,
      needs: on ? [...current.needs.filter((need) => need !== code), code] : current.needs.filter((need) => need !== code),
    }));

  if (load.kind === 'loading') return <p>Loading the case.</p>;
  if (load.kind === 'failed') return <p role="alert">This case could not be loaded.</p>;

  const referrerLabel = labelOf(REFERRERS, draft.referrerType) ?? 'Caller not yet recorded';

  return (
    <section className={styles.form} aria-label="Patient needs">
      <CallBar openedAt={openedAt} referrer={referrerLabel} />
      <form onSubmit={save} noValidate>
        <h1 className={styles.legend}>Patient needs</h1>

        <fieldset className={styles.group}>
          <legend className={styles.legend}>Who is calling?</legend>
          <div className={styles.chips}>
            {REFERRERS.map((referrer) => (
              <Chip
                key={referrer.code}
                pressed={draft.referrerType === referrer.code}
                onPressedChange={() => setReferrer(referrer.code)}
                dataEl={`ADV-NEEDS-REFERRER-${referrer.id}`}
              >
                {referrer.label}
              </Chip>
            ))}
          </div>
        </fieldset>

        <fieldset className={styles.group}>
          <legend className={styles.legend}>Age</legend>
          <div className={styles.chips}>
            {AGE_BANDS.map((band) => (
              <Chip
                key={band.code}
                pressed={draft.ageBand === band.code}
                onPressedChange={() => setAge(band.code)}
                dataEl={`ADV-NEEDS-AGE-${band.id}`}
              >
                {band.label}
              </Chip>
            ))}
          </div>
        </fieldset>

        <div className={styles.field}>
          <label className={styles.label} htmlFor={POSTCODE_ID}>
            Where is the patient? Postcode
          </label>
          <input
            id={POSTCODE_ID}
            name="postcode"
            type="text"
            className={styles.input}
            autoComplete="off"
            spellCheck={false}
            value={draft.postcode}
            onChange={(event) => setDraft((current) => ({ ...current, postcode: event.target.value }))}
            onBlur={onPostcodeBlur}
            aria-invalid={postcodeError ? 'true' : undefined}
            aria-describedby={postcodeError ? POSTCODE_ERROR_ID : undefined}
            data-el="ADV-NEEDS-POSTCODE"
          />
          {postcodeError ? (
            <p id={POSTCODE_ERROR_ID} className={styles.error}>
              {POSTCODE_ERROR}
            </p>
          ) : null}
        </div>

        <fieldset className={styles.group}>
          <legend className={styles.legend}>What do they need?</legend>
          <div className={styles.chips}>
            {NEEDS.filter((need) => !need.more).map((need) => (
              <Chip
                key={need.code}
                pressed={draft.needs.includes(need.code)}
                onPressedChange={(on) => toggleNeed(need.code, on)}
                dataEl={`ADV-NEEDS-NEED-${need.id}`}
              >
                {need.label}
              </Chip>
            ))}
            <button
              type="button"
              className={styles.more}
              aria-expanded={showMore}
              onClick={() => setShowMore((open) => !open)}
            >
              More needs
            </button>
            {showMore
              ? NEEDS.filter((need) => need.more).map((need) => (
                  <Chip
                    key={need.code}
                    pressed={draft.needs.includes(need.code)}
                    onPressedChange={(on) => toggleNeed(need.code, on)}
                    dataEl={`ADV-NEEDS-NEED-${need.id}`}
                  >
                    {need.label}
                  </Chip>
                ))
              : null}
          </div>
        </fieldset>

        <fieldset className={styles.group}>
          <legend className={styles.legend}>How soon?</legend>
          <div className={styles.chips}>
            {URGENCIES.map((urgency) => (
              <Chip
                key={urgency.code}
                pressed={draft.urgency === urgency.code}
                onPressedChange={() => setUrgency(urgency.code)}
                dataEl={`ADV-NEEDS-URGENCY-${urgency.id}`}
              >
                {urgency.label}
              </Chip>
            ))}
          </div>
        </fieldset>

        <p className={styles.note}>
          No patient name is stored. Postcode and needs are cleared after the call record closes.
        </p>

        {message === 'conflict' ? (
          <p role="alert" className={styles.error}>
            This case changed in another window. Reload to see the latest.
          </p>
        ) : null}
        {message === 'failed' ? (
          <p role="alert" className={styles.error}>
            The case could not be saved. Try again.
          </p>
        ) : null}

        <Button type="submit" variant="primary" busy={saving} disabled={!canContinue} dataEl="ADV-NEEDS-CONTINUE-BTN">
          See options
        </Button>
      </form>
    </section>
  );
}
