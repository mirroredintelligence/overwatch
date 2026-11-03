import { ChoiceGroup, Field, StepFrame, type StepProps } from './StepService';
import styles from './StepCriteria.module.css';
import { DistrictCheckPanel } from './DistrictCheck';

// Step 3 of "Add a service", "Who it takes" (boards/lead/AddService.dc.html): the needs accepted and not accepted,
// the ages, the postcode districts and the date the criteria are reviewed by. The board also asks who owns the
// criteria; the back end has no such field yet (LDR-03), so it is not asked. The step holds no state.

export type StepCriteriaProps = StepProps & {
  toggle: (key: 'accepts' | 'excludes', value: string) => void;
};

export const ACCEPTS: [string, string][] = [
  ['fall-no-injury', 'Fall, no injury'],
  ['frailty', 'Frailty'],
  ['wound-care', 'Wound care'],
  ['iv-therapy', 'IV therapy'],
  ['palliative', 'Palliative'],
  ['dementia', 'Dementia'],
];

export const EXCLUDES: [string, string][] = [
  ['suspected-fracture', 'Suspected fracture'],
  ['head-injury-anticoagulants', 'Head injury on anticoagulants'],
  ['iv-therapy', 'Needs IV therapy'],
  ['infection-isolation', 'Infection isolation'],
];

export function StepCriteria({ values, set, toggle, errors, summaryRef, onNext, onBack }: StepCriteriaProps) {
  const errorFor = (field: string) => errors.find((error) => error.field === field)?.message;
  return (
    <StepFrame
      title="Who it takes"
      errors={errors}
      summaryRef={summaryRef}
      onNext={onNext}
      onBack={onBack}
      nextLabel="Next: check"
    >
      <ChoiceGroup
        id="lead-add-accepts"
        label="Needs you accept"
        choices={ACCEPTS}
        selected={values.accepts}
        onPick={(value) => toggle('accepts', value)}
        idPrefix="LEAD-ADD-ACCEPTS"
        error={errorFor('lead-add-accepts')}
      />
      <ChoiceGroup
        label="Needs you do not accept"
        choices={EXCLUDES}
        selected={values.excludes}
        onPick={(value) => toggle('excludes', value)}
        idPrefix="LEAD-ADD-EXCLUDES"
      />
      <div className={styles.row}>
        <div className={styles.age}>
          <Field id="lead-add-age-min" label="Youngest age" error={errorFor('lead-add-age-min')}>
            {(props) => <input {...props} inputMode="numeric" value={values.ageMin} onChange={(e) => set('ageMin', e.target.value)} />}
          </Field>
        </div>
        <div className={styles.age}>
          <Field id="lead-add-age-max" label="Oldest age" hint="Leave blank for no limit" error={errorFor('lead-add-age-max')}>
            {(props) => <input {...props} inputMode="numeric" value={values.ageMax} onChange={(e) => set('ageMax', e.target.value)} />}
          </Field>
        </div>
        <div className={styles.wide}>
          <Field
            id="lead-add-districts"
            label="Postcode districts"
            hint="Whole districts, like DT4. Separate with commas."
            error={errorFor('lead-add-districts')}
          >
            {(props) => <input {...props} value={values.districts} onChange={(e) => set('districts', e.target.value)} />}
          </Field>
          <DistrictCheckPanel text={values.districts} />
        </div>
      </div>
      <Field
        id="lead-add-review"
        label="Review criteria by"
        hint="Advisors see a flag when this date passes"
        error={errorFor('lead-add-review')}
      >
        {(props) => <input {...props} type="date" value={values.reviewBy} onChange={(e) => set('reviewBy', e.target.value)} />}
      </Field>
      <p className={styles.pilot}>Services with neither text nor email are outside the MVP.</p>
    </StepFrame>
  );
}
