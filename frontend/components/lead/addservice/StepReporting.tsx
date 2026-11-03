import { ChoiceGroup, Field, StepFrame, labelOf, type StepProps } from './StepService';
import styles from './StepReporting.module.css';

// Step 2 of "Add a service", "Who reports, and how" (boards/lead/AddService.dc.html): text or email, the number or
// the address, the role that holds the phone and the usual cadence. The invitation is only texted after the
// service is added, and the card says so.

export const CHANNELS: [string, string][] = [
  ['text', 'Text'],
  ['email', 'Email'],
];

export const CADENCES: [string, string][] = [
  ['every-2-hrs', 'Every 2 hrs'],
  ['twice-a-day', 'Twice a day'],
  ['once-a-day', 'Once a day'],
];

export const cadenceLabel = (value: string | null) => labelOf(CADENCES, value);

export function StepReporting({ values, set, errors, summaryRef, onNext, onBack }: StepProps) {
  const errorFor = (field: string) => errors.find((error) => error.field === field)?.message;
  return (
    <StepFrame
      title="Who reports, and how"
      errors={errors}
      summaryRef={summaryRef}
      onNext={onNext}
      onBack={onBack}
      nextLabel="Next: who it takes"
    >
      <ChoiceGroup
        label="How will they report?"
        choices={CHANNELS}
        selected={values.channel}
        onPick={(value) => set('channel', value as 'text' | 'email')}
        idPrefix="LEAD-ADD-CHANNEL"
      />
      <div className={styles.pair}>
        {values.channel === 'text' ? (
          <Field id="lead-add-mobile" label="Mobile number for text" hint="A ward or team phone is best." error={errorFor('lead-add-mobile')}>
            {(props) => (
              <input
                {...props}
                inputMode="tel"
                autoComplete="off"
                value={values.mobile}
                onChange={(e) => set('mobile', e.target.value)}
              />
            )}
          </Field>
        ) : (
          <Field id="lead-add-email" label="Email" error={errorFor('lead-add-email')}>
            {(props) => (
              <input {...props} type="email" autoComplete="off" value={values.email} onChange={(e) => set('email', e.target.value)} />
            )}
          </Field>
        )}
        <Field id="lead-add-role" label="Who holds this phone" hint="A role, never a person's name." error={errorFor('lead-add-role')}>
          {(props) => <input {...props} value={values.roleName} onChange={(e) => set('roleName', e.target.value)} />}
        </Field>
      </div>
      <ChoiceGroup
        id="lead-add-cadence"
        label="Usual cadence"
        choices={CADENCES}
        selected={values.cadence}
        onPick={(value) => set('cadence', value)}
        idPrefix="LEAD-ADD-CADENCE"
        error={errorFor('lead-add-cadence')}
      />
      <p className={styles.note}>
        After you add the service, you can text the phone an invitation to set up in about three minutes. Nothing is sent now.
      </p>
    </StepFrame>
  );
}
