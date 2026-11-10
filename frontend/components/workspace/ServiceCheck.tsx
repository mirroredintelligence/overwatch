'use client';

import { useEffect, useRef, useState, type ReactElement } from 'react';
import { PostcodePicker } from '@/components/advisor/PostcodePicker';
import { type NeedCode } from '@/lib/advisor/codes';
import { normalisePostcode } from '@/lib/advisor/postcode';
import { locatePostcode, suggestPostcodes } from '@/lib/advisor/postcodeSuggest';
import { checkService } from '@/lib/advisor/v2/browser';
import type { FitCheck } from '@/lib/advisor/v2/check';
import { TriageCard } from './TriageCard';
import styles from './ServiceCheck.module.css';
import { useWorkspace } from './WorkspaceProvider';

// "Book a slot" on the service page (DEC-1377): the triage card in the assistant thread, then the answer for this one
// service. The page does not change. The postcode is asked as well as the age and need because the service's catchment
// is one of its hard criteria. The check starts by itself once the criteria are complete (as the finder does); the
// back end runs the rules and the browser only shows the answer. Nothing is stored: the criteria stay in the
// provider's memory and go in the body of one POST. Booking itself is not here: the answer says to phone.

const POSTCODE_ID = 'sc-postcode';
const POSTCODE_LIST_ID = 'sc-postcode-suggestions';
const POSTCODE_HELP_ID = 'sc-postcode-help';
const POSTCODE_HELP = 'Enter a full postcode, for example DT4 8XX.';
const CAVEAT = 'The criteria are a guide. The receiving service confirms whether it can take the patient.';
const NO_BOOKING = 'Booking is not made from this page yet. Phone the service to book.';
const FAILED = 'The check could not be made. Change a choice to try again, or phone the service.';

type Check = { key: string; kind: 'checking' } | { key: string; kind: 'failed' } | { key: string; kind: 'done'; read: FitCheck };

export function ServiceCheck({ serviceId, onClose }: { serviceId: string; onClose: () => void }): ReactElement {
  const { criteria, setCriteria, resetCriteria, criteriaComplete } = useWorkspace();
  const { age, postcode, needs, urgency } = criteria;
  const [step, setStep] = useState<'age' | 'need'>('age');
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [located, setLocated] = useState<'found' | 'not-found' | 'unavailable' | null>(null);
  const [result, setResult] = useState<Check | null>(null);
  const lastKey = useRef<string | null>(null);

  const full = normalisePostcode(postcode);
  const ageOk = age !== null && full !== null;
  const needsKey = [...needs].sort().join(',');
  const key = `${serviceId}|${full ?? ''}|${age ?? ''}|${needsKey}|${urgency ?? ''}`;
  const current = result !== null && result.key === key ? result : null;

  // The check: once for each distinct set of criteria, as soon as they are complete.
  useEffect(() => {
    if (step !== 'need' || !criteriaComplete || full === null || age === null || urgency === null) return;
    if (lastKey.current === key) return;
    lastKey.current = key;
    setResult({ key, kind: 'checking' });
    void checkService(serviceId, { postcode: full, ageBand: age, needs, urgency }).then((read) => {
      setResult(read === null ? { key, kind: 'failed' } : { key, kind: 'done', read });
    });
    // The criteria are compared by key; the values read here are the ones of the render that changed it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, criteriaComplete, key]);

  function onType(typed: string) {
    setCriteria({ postcode: typed });
    setLocated(null);
    void suggestPostcodes(typed).then(setSuggestions);
  }

  function onPick(picked: string) {
    setCriteria({ postcode: picked });
    setSuggestions([]);
    setLocated(null);
    void locatePostcode(picked).then((place) => setLocated(place.status));
  }

  function onBlur() {
    const normal = normalisePostcode(postcode);
    if (normal === null) {
      setLocated(null);
      return;
    }
    setCriteria({ postcode: normal });
    void locatePostcode(normal).then((place) => setLocated(place.status));
  }

  function toggleNeed(code: NeedCode) {
    setCriteria({ needs: needs.includes(code) ? needs.filter((item) => item !== code) : [...needs, code] });
  }

  function another() {
    resetCriteria();
    lastKey.current = null;
    setResult(null);
    setLocated(null);
    setStep('age');
  }

  if (step === 'need' && current !== null && current.kind !== 'checking') {
    return (
      <div className={styles.card} data-el="WS-SERVICE-CHECK">
        {current.kind === 'failed' ? <p role="alert">{FAILED}</p> : <Answer check={current.read} />}
        <div className={styles.row}>
          <button type="button" className={styles.button} onClick={another}>
            Check another patient
          </button>
          <button type="button" className={styles.button} onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    );
  }

  const help =
    located === 'found'
      ? 'Postcode found.'
      : located === 'not-found'
        ? 'Not found. Check the postcode.'
        : located === 'unavailable'
          ? 'The postcode lookup is unavailable. The check still uses the postcode as typed.'
          : full !== null
            ? 'Postcode accepted.'
            : POSTCODE_HELP;

  const postcodeSlot = (
    <div className={styles.postcode}>
      <label htmlFor={POSTCODE_ID} className={styles.label}>
        Postcode
      </label>
      <PostcodePicker
        id={POSTCODE_ID}
        listId={POSTCODE_LIST_ID}
        value={postcode}
        options={suggestions}
        invalid={false}
        describedBy={POSTCODE_HELP_ID}
        dataEl="SVC-CHECK-POSTCODE"
        onType={onType}
        onPick={onPick}
        onBlur={onBlur}
      />
      <p id={POSTCODE_HELP_ID} className={styles.help} aria-live="polite">
        {help}
      </p>
    </div>
  );

  return (
    <div data-el="WS-SERVICE-CHECK">
      <TriageCard
        step={step}
        age={age}
        needs={needs}
        urgency={urgency}
        postcodeSlot={postcodeSlot}
        canNext={ageOk}
        onAge={(code) => setCriteria({ age: code })}
        onToggleNeed={toggleNeed}
        onUrgency={(code) => setCriteria({ urgency: code })}
        onNext={() => setStep('need')}
      />
      {current?.kind === 'checking' ? (
        <p role="status" className={styles.help}>
          Checking.
        </p>
      ) : null}
    </div>
  );
}

function Answer({ check }: { check: FitCheck }): ReactElement {
  return (
    <div className={styles.answer} role="status">
      <h3 className={styles.heading}>{check.fits ? 'This patient fits this service' : 'This patient does not fit this service'}</h3>
      {check.fits ? (
        check.fitsNeeds.length > 0 ? (
          <p className={styles.line}>{`Takes: ${check.fitsNeeds.join(', ')}.`}</p>
        ) : null
      ) : (
        <ul className={styles.list} aria-label="Reasons">
          {check.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      )}
      {check.warnings.length > 0 ? (
        <ul className={styles.list} aria-label="Warnings">
          {check.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      ) : null}
      {check.fits ? (
        <>
          <p className={styles.line}>{check.phone === null ? 'No phone number is held for this service.' : `Phone: ${check.phone}`}</p>
          <p className={styles.note}>{NO_BOOKING}</p>
        </>
      ) : null}
      <p className={styles.note}>{CAVEAT}</p>
    </div>
  );
}
