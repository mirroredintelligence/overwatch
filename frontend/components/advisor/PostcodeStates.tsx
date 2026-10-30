import { Button } from '@/components/ui/Button';
import styles from './map.module.css';

// The two states the map gives when a postcode cannot be used (W50). Each names a next step; a call is
// never ended here (the same rule as the no-service-fits state, W16).

export function PostcodeNotFound({ caseId, onAskClinical }: { caseId: string; onAskClinical: () => void }) {
  const id = encodeURIComponent(caseId);
  return (
    <section className={styles.screen} aria-labelledby="postcode-not-found-heading">
      <h2 id="postcode-not-found-heading" className={styles.heading}>
        We could not find that postcode
      </h2>
      <p className={styles.sub}>Check it with the caller, or choose the district.</p>
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
}: {
  caseId: string;
  postcode: string;
  onAskClinical: () => void;
}) {
  const id = encodeURIComponent(caseId);
  return (
    <section className={styles.screen} aria-labelledby="out-of-area-heading">
      <h2 id="out-of-area-heading" className={styles.heading}>
        No service covers this area
      </h2>
      <p className={styles.sub}>
        {`${postcode} is outside the areas the services here cover. Do not leave the caller without a next step.`}
      </p>
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
