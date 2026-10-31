'use client';

import { useRouter } from 'next/navigation';
import { type FormEvent, useCallback, useEffect, useState } from 'react';
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
  SCORE_CORRECTION_REASONS,
  type ScoreCorrectionReasonCode,
  URGENCIES,
  type UrgencyCode,
} from '@/lib/advisor/codes';
import { bffFetch, newIdempotencyKey } from '@/lib/advisor/browser';
import { normalisePostcode } from '@/lib/advisor/postcode';
import type { Score } from '@/lib/advisor/scores';
import { scoreText } from '@/lib/advisor/summary';
import { CallBar } from './CallBar';
import { ScorePickers } from './ScorePickers';
import styles from './NeedsForm.module.css';

// The needs form (W11): who is calling, age, postcode, needs and how soon. Nothing is typed except
// the postcode. The form is not editable until the case has been read, so a save never overwrites
// a case the page has not seen. A save sends the ETag it read as If-Match and a key of its own (W11).
// The back end keeps the postcode DISTRICT only (DEC-398), so the form says which district is on record
// and sends a postcode only when one is typed; a recorded score is shown as text and is changed only
// by a correction with a reason, the first value kept in the audit (Q7, DEC-1171); a closed case cannot
// change, so it is not a form at all. A save refused because someone else changed the case first says
// so and keeps nothing: the advisor reads the case again (H-192, DEC-1172).

const POSTCODE_ERROR = 'Enter a full postcode, for example DT4 8XX';
const POSTCODE_ERROR_ID = 'needs-postcode-error';
const POSTCODE_ID = 'needs-postcode';

type Draft = {
  referrerType: ReferrerCode | null;
  ageBand: AgeCode | null;
  postcode: string;
  needs: NeedCode[];
  urgency: UrgencyCode | null;
  scores: Score[];
};

/** True when a score of a method already recorded is given another value (a correction). */
function changesRecorded(recorded: Score[], given: Score[]): boolean {
  return recorded.some((was) => {
    const now = given.find((score) => score.method === was.method);
    return now !== undefined && now.value !== was.value;
  });
}

/** True when a method already recorded is missing from the draft (an invalid entry): not saved. */
function dropsRecorded(recorded: Score[], given: Score[]): boolean {
  return recorded.some((was) => !given.some((score) => score.method === was.method));
}

type Load = { kind: 'loading' } | { kind: 'ready'; view: CaseView } | { kind: 'failed' };

const EMPTY: Draft = { referrerType: null, ageBand: null, postcode: '', needs: [], urgency: null, scores: [] };

function draftFrom(view: CaseView): Draft {
  return {
    referrerType: view.referrerType,
    ageBand: view.ageBand,
    // The field starts empty: the district on record is not a postcode to edit, it is said beside it.
    postcode: '',
    needs: view.needs,
    urgency: view.urgency,
    scores: view.scores,
  };
}

/** The coded save, or null while any part is still unset or the postcode is neither full nor on record. */
function inputFrom(draft: Draft, postcode: string | null, districtOnRecord: boolean): CaseInput | null {
  if (draft.referrerType === null || draft.ageBand === null || draft.urgency === null) return null;
  if ((postcode === null && !districtOnRecord) || draft.needs.length === 0) return null;
  return {
    referrerType: draft.referrerType,
    ageBand: draft.ageBand,
    postcode,
    needs: draft.needs,
    urgency: draft.urgency,
    scores: draft.scores,
  };
}

/** The save as sent: no postcode leaves the district on record, and no reason key unless scores were corrected. */
function bodyOf(input: CaseInput): Record<string, unknown> {
  const body: Record<string, unknown> = { ...input };
  if (input.postcode === null) delete body.postcode;
  if (!input.scoreCorrectionReason) delete body.scoreCorrectionReason;
  return body;
}

export function NeedsForm({ caseId }: { caseId: string }) {
  const router = useRouter();
  const [load, setLoad] = useState<Load>({ kind: 'loading' });
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [showMore, setShowMore] = useState(false);
  const [postcodeError, setPostcodeError] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<'conflict' | 'failed' | null>(null);
  const [correcting, setCorrecting] = useState(false);
  const [reason, setReason] = useState<ScoreCorrectionReasonCode | null>(null);
  // The clock the call bar falls back to when the back end gave no open time: when the case was read.
  const [readAt, setReadAt] = useState('');

  // Reads the case and puts it on screen as it is now: the draft, the correction and any message start again.
  const read = useCallback(
    (isLive: () => boolean) =>
      bffFetch<CaseView>(`/api/bff/cases/${encodeURIComponent(caseId)}`).then((reply) => {
        if (!isLive()) return;
        if (reply.ok) {
          setReadAt(new Date().toISOString());
          setLoad({ kind: 'ready', view: reply.body });
          setDraft(draftFrom(reply.body));
          setCorrecting(false);
          setReason(null);
          setMessage(null);
        } else {
          setLoad({ kind: 'failed' });
        }
      }),
    [caseId],
  );

  useEffect(() => {
    let live = true;
    void read(() => live);
    return () => {
      live = false;
    };
  }, [read]);

  async function readAgain() {
    setSaving(true);
    await read(() => true);
    setSaving(false);
  }

  const view = load.kind === 'ready' ? load.view : null;
  const district = view?.postcode ?? null;
  const postcode = normalisePostcode(draft.postcode);
  const recorded = view?.scores ?? [];
  const corrected = recorded.length > 0 && changesRecorded(recorded, draft.scores);
  // A changed recorded score needs its reason; a method recorded and now invalid is not saved.
  const scoresReady = !(corrected && reason === null) && !dropsRecorded(recorded, draft.scores);
  const base = inputFrom(draft, postcode, district !== null);
  const input: CaseInput | null =
    base === null || !scoresReady ? null : corrected ? { ...base, scoreCorrectionReason: reason } : base;
  const canContinue = load.kind === 'ready' && input !== null && !saving && message !== 'conflict';

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
      body: bodyOf(input),
      ifMatch: load.view.etag ?? undefined,
      idempotencyKey: newIdempotencyKey(),
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
  if (load.view.closed) {
    return (
      <section className={styles.form} aria-label="Patient needs">
        <h1 className={styles.legend}>This call is closed.</h1>
        <p className={styles.note}>The postcode and needs were cleared when it closed. A closed call cannot be changed.</p>
        <Button variant="primary" href="/advisor">
          Start a new call
        </Button>
      </section>
    );
  }

  const referrerLabel = labelOf(REFERRERS, draft.referrerType) ?? 'Caller not yet recorded';

  return (
    <section className={styles.form} aria-label="Patient needs">
      <CallBar openedAt={load.view.openedAt ?? readAt} referrer={referrerLabel} />
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
          {district !== null ? (
            <p className={styles.note}>{`On record: postcode district ${district}. Type the full postcode only to change it.`}</p>
          ) : null}
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

        {recorded.length === 0 ? (
          <ScorePickers value={draft.scores} onChange={(scores) => setDraft((current) => ({ ...current, scores }))} />
        ) : (
          <>
            <p className={styles.note}>{`Recorded as the referrer gave them: ${recorded.map(scoreText).join('; ')}.`}</p>
            {load.view.scoreCorrections > 0 ? (
              <p className={styles.note}>
                {`Corrected ${load.view.scoreCorrections} ${load.view.scoreCorrections === 1 ? 'time' : 'times'}. The score first recorded is kept in the record.`}
              </p>
            ) : null}
            {correcting ? (
              <>
                <ScorePickers
                  value={draft.scores}
                  onChange={(scores) => setDraft((current) => ({ ...current, scores }))}
                  recordedMethods={recorded.map((score) => score.method)}
                />
                <fieldset className={styles.group}>
                  <legend className={styles.legend}>Why is the score being corrected?</legend>
                  <div className={styles.chips}>
                    {SCORE_CORRECTION_REASONS.map((item) => (
                      <label key={item.code} className={styles.reason}>
                        <input
                          type="radio"
                          name="score-correction-reason"
                          checked={reason === item.code}
                          onChange={() => setReason(item.code)}
                          data-el={`ADV-SCORE-REASON-${item.code}`}
                        />
                        {item.label}
                      </label>
                    ))}
                  </div>
                  <p className={styles.note}>
                    {corrected && reason === null
                      ? 'Choose why before saving a changed score.'
                      : 'The score first recorded is kept in the record. A reason is needed only when a recorded score changes.'}
                  </p>
                </fieldset>
              </>
            ) : (
              <button type="button" className={styles.more} onClick={() => setCorrecting(true)}>
                Correct a score
              </button>
            )}
          </>
        )}

        <p className={styles.note}>
          No patient name is stored. Postcode and needs are cleared after the call record closes.
        </p>

        {message === 'conflict' ? (
          <div role="alert" className={styles.error}>
            <p>Someone changed this case since you opened it. Nothing of yours was saved.</p>
            <button type="button" className={styles.more} onClick={() => void readAgain()}>
              Read the case again
            </button>
          </div>
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
