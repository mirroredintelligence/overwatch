import { useId, useState } from 'react';
import { Button } from '@/components/ui/Button';
import type { PostcodeChange } from '@/lib/advisor/postcodeChange';
import styles from './PostcodeStates.module.css';

// The two states the map and the list give when a postcode cannot be used (W50). Each names a next step; a
// call is never ended here (the same rule as the no-service-fits state, W16). When the back end offered
// districts the services cover, the advisor can choose one and the options run again (W9H, DEC-1045): a
// chip is a button that saves the district on the case, never a postcode. With no districts given the
// state is as it was.

type DistrictProps = {
  /** The districts to choose from, in the order to show them. Omitted: the state offers none. */
  districts?: string[];
  /** Saves the chosen district and runs the options again; true when it was kept. */
  onChooseDistrict?: (district: string) => Promise<boolean>;
  /** Tries a postcode typed here and runs the options again. Omitted: the state offers no field. */
  onSearchAgain?: (postcode: string) => Promise<PostcodeChange>;
};

const CHOICE_NOTE = 'Options will use the district, with a wider travel range.';
const CHOICE_FAILED = 'We could not use that district. Try again, or choose another.';

function DistrictChips({ districts, onChooseDistrict }: { districts: string[]; onChooseDistrict: (district: string) => Promise<boolean> }) {
  const [using, setUsing] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  const choose = async (district: string) => {
    if (using !== null) return;
    setUsing(district);
    setFailed(false);
    const kept = await onChooseDistrict(district);
    // Kept: the screen changes with the new options. Not kept: say so and offer the chips again.
    if (!kept) {
      setFailed(true);
      setUsing(null);
    }
  };

  return (
    <>
      <fieldset className={styles.chips}>
        <legend className={styles.chipsLegend}>Choose the district</legend>
        {districts.map((district) => (
          <button key={district} type="button" className={styles.chip} disabled={using !== null} onClick={() => void choose(district)} data-el={`ADV-DISTRICT-${district}`}>
            {district}
          </button>
        ))}
      </fieldset>
      <p className={styles.note}>{CHOICE_NOTE}</p>
      {using !== null ? <p role="status">{`Using ${using}.`}</p> : null}
      {failed ? <p role="alert">{CHOICE_FAILED}</p> : null}
    </>
  );
}

const SEARCH_MESSAGES: Record<Exclude<PostcodeChange, 'saved'>, string> = {
  invalid: 'Enter a full postcode, like DT4 8XX.',
  conflict: 'The case changed while you were typing. Read it again, then try again.',
  failed: 'The postcode could not be tried. Try again.',
};

// The postcode typed again in place (MapWeb 3): one field and one button. A postcode that is kept runs the
// options again and the screen changes; one that is not is said, in words, beside the field.
function PostcodeSearch({ onSearchAgain }: { onSearchAgain: (postcode: string) => Promise<PostcodeChange> }) {
  const fieldId = useId();
  const [typed, setTyped] = useState('');
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const search = async () => {
    if (busy) return;
    setBusy(true);
    setProblem(null);
    const result = await onSearchAgain(typed);
    if (result !== 'saved') {
      setProblem(SEARCH_MESSAGES[result]);
      setBusy(false);
    }
  };

  return (
    <div className={styles.search}>
      <label htmlFor={fieldId} className={styles.chipsLegend}>
        Postcode
      </label>
      <input
        id={fieldId}
        type="text"
        className={styles.field}
        value={typed}
        autoComplete="off"
        aria-invalid={problem === null ? undefined : true}
        aria-describedby={problem === null ? undefined : `${fieldId}-problem`}
        onChange={(event) => setTyped(event.target.value)}
        data-el="ADV-POSTCODE-FIX"
      />
      {problem === null ? null : (
        <p id={`${fieldId}-problem`} role="alert">
          {problem}
        </p>
      )}
      <div className={styles.actions}>
        <Button variant="secondary" busy={busy} onClick={() => void search()} dataEl="ADV-POSTCODE-SEARCH-BTN">
          Search again
        </Button>
      </div>
    </div>
  );
}

function Choice({ districts, onChooseDistrict }: DistrictProps) {
  if (districts === undefined || onChooseDistrict === undefined || districts.length === 0) return null;
  return <DistrictChips districts={districts} onChooseDistrict={onChooseDistrict} />;
}

export function PostcodeNotFound({
  caseId,
  onAskClinical,
  districts,
  onChooseDistrict,
  onSearchAgain,
}: { caseId: string; onAskClinical: () => void } & DistrictProps) {
  const id = encodeURIComponent(caseId);
  // With districts to choose, the spec's sentence; with none to choose from, it does not point at them.
  const offered = districts === undefined || districts.length > 0;
  return (
    <section className={styles.screen} aria-labelledby="postcode-not-found-heading">
      <h2 id="postcode-not-found-heading" className={styles.heading}>
        We could not find that postcode
      </h2>
      <p className={styles.sub}>{offered ? 'Check it with the caller, or choose the district.' : 'Check it with the caller.'}</p>
      {onSearchAgain === undefined ? null : <PostcodeSearch onSearchAgain={onSearchAgain} />}
      <Choice districts={districts} onChooseDistrict={onChooseDistrict} />
      <ul className={styles.steps} aria-label="Next steps">
        <li className={styles.step}>
          <Button variant="primary" dataEl="ADV-NOFIT-CLINICAL-BTN" onClick={() => onAskClinical()}>
            Ask a clinical advisor
          </Button>
        </li>
        <li className={styles.step}>
          <Button variant="secondary" href={`/advisor/case/${id}`}>
            Change the postcode
          </Button>
        </li>
        <li className={styles.step}>
          <Button variant="secondary" href="/advisor/board" dataEl="ADV-NOFIT-PHONE-BTN">
            Phone a service you know has space
          </Button>
        </li>
        <li className={styles.step}>
          <Button variant="secondary" href={`/advisor/case/${id}/finish?outcome=no-service-fits`} dataEl="ADV-NOFIT-OTHER-BTN">
            Other routes under local protocol
          </Button>
        </li>
      </ul>
    </section>
  );
}

export function OutOfArea({
  caseId,
  postcode,
  onAskClinical,
  districts,
  onChooseDistrict,
}: {
  caseId: string;
  postcode: string;
  onAskClinical: () => void;
} & DistrictProps) {
  const id = encodeURIComponent(caseId);
  return (
    <section className={styles.screen} aria-labelledby="out-of-area-heading">
      <h2 id="out-of-area-heading" className={styles.heading}>
        No service covers this area
      </h2>
      <p className={styles.sub}>
        {`${postcode} is outside the areas the services here cover. Do not leave the caller without a next step.`}
      </p>
      <Choice districts={districts} onChooseDistrict={onChooseDistrict} />
      <ul className={styles.steps} aria-label="Next steps">
        <li className={styles.step}>
          <Button variant="primary" dataEl="ADV-NOFIT-CLINICAL-BTN" onClick={() => onAskClinical()}>
            Ask a clinical advisor
          </Button>
        </li>
        <li className={styles.step}>
          <Button variant="secondary" href={`/advisor/case/${id}/finish?outcome=out-of-area`} dataEl="ADV-NOFIT-OTHER-BTN">
            Other routes under local protocol
          </Button>
        </li>
        <li className={styles.step}>
          <Button variant="secondary" href={`/advisor/case/${id}`}>
            Change the postcode
          </Button>
        </li>
      </ul>
      <p className={styles.note}>Out-of-area referrals are recorded as an outcome so the coverage can be reviewed.</p>
    </section>
  );
}
