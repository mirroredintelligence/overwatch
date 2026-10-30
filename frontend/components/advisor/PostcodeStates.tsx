import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import styles from './map.module.css';

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

function Choice({ districts, onChooseDistrict }: DistrictProps) {
  if (districts === undefined || onChooseDistrict === undefined || districts.length === 0) return null;
  return <DistrictChips districts={districts} onChooseDistrict={onChooseDistrict} />;
}

export function PostcodeNotFound({
  caseId,
  onAskClinical,
  districts,
  onChooseDistrict,
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
      <Choice districts={districts} onChooseDistrict={onChooseDistrict} />
      <div className={styles.actions}>
        <Button variant="secondary" href={`/advisor/case/${id}`}>
          Change the postcode
        </Button>
        <Button variant="secondary" href={`/advisor/case/${id}/finish?outcome=no-service-fits`} dataEl="ADV-NOFIT-OTHER-BTN">
          Other routes under local protocol
        </Button>
        <Button variant="primary" dataEl="ADV-NOFIT-CLINICAL-BTN" onClick={() => onAskClinical()}>
          Ask a clinical advisor
        </Button>
      </div>
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
      <div className={styles.actions}>
        <Button variant="primary" dataEl="ADV-NOFIT-CLINICAL-BTN" onClick={() => onAskClinical()}>
          Ask a clinical advisor
        </Button>
        <Button variant="secondary" href={`/advisor/case/${id}/finish?outcome=out-of-area`} dataEl="ADV-NOFIT-OTHER-BTN">
          Other routes under local protocol
        </Button>
        <Button variant="secondary" href={`/advisor/case/${id}`}>
          Change the postcode
        </Button>
      </div>
      <p className={styles.note}>Out-of-area referrals are recorded as an outcome so the coverage can be reviewed.</p>
    </section>
  );
}
