import { useId, useRef, type FormEvent, type ReactNode, type Ref } from 'react';
import { ErrorSummary, type FieldError } from '@/components/lead/ErrorSummary';
import { Button } from '@/components/ui/Button';
import { Chip } from '@/components/ui/Chip';
import type { ServiceValues } from '@/lib/lead/serviceForm';
import styles from './StepService.module.css';

// Step 1 of "Add a service", "The service" (boards/lead/AddService.dc.html), and the pieces every step shares:
// the card (StepFrame), a field with its hint and problem (Field) and the chip groups. The step holds no state;
// the page's one form state (useServiceFormState) is passed in.

export type SetValue = <K extends keyof ServiceValues>(key: K, value: ServiceValues[K]) => void;

export type StepProps = {
  values: ServiceValues;
  set: SetValue;
  /** The problems of this step, shown in a summary at the top and by each field. */
  errors: FieldError[];
  summaryRef?: Ref<HTMLDivElement>;
  /** Next was pressed or Enter was typed; `viaKeyboard` is true for Enter, which changes step with no animation. */
  onNext: (viaKeyboard: boolean) => void;
  onBack?: () => void;
};

export const CATEGORIES: [string, string][] = [
  ['urgent-community-response', 'Urgent community response'],
  ['same-day-emergency-care', 'Same day emergency care'],
  ['inpatient-beds', 'Inpatient beds'],
  ['hospital-at-home-or-virtual-ward', 'Hospital at home or virtual ward'],
  ['reablement', 'Reablement'],
  ['other', 'Other'],
];

// "Virtual beds free" is the same measure as "Beds free" (free-beds); the unit label carries the
// difference. The screen offers the four measures the back end counts (DEC-655).
export const MEASURES: [string, string][] = [
  ['referrals-acceptable', 'Referrals in the next 2 hrs'],
  ['free-beds', 'Beds free'],
  ['free-slots', 'Slots left today'],
  ['packages-free', 'Packages available'],
];

export const labelOf = (choices: [string, string][], value: string | null): string =>
  choices.find(([key]) => key === value)?.[1] ?? '';

export function Field({
  id,
  label,
  hint,
  error,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  children: (props: { id: string; className: string; 'aria-describedby': string | undefined; 'aria-invalid': true | undefined }) => ReactNode;
}) {
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const describedBy = [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(' ') || undefined;
  return (
    <div className={styles.field}>
      <label htmlFor={id} className={styles.label}>
        {label}
      </label>
      {hint ? (
        <p id={hintId} className={styles.hint}>
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} className={styles.error}>
          {error}
        </p>
      ) : null}
      {children({ id, className: styles.input, 'aria-describedby': describedBy, 'aria-invalid': error ? true : undefined })}
    </div>
  );
}

/** A group of chips: one chosen (`selected` a string) or any number (`selected` a list). */
export function ChoiceGroup({
  id,
  label,
  choices,
  selected,
  onPick,
  idPrefix,
  error,
}: {
  /** The id the problem summary links to: the group, whose first chip takes focus. */
  id?: string;
  label: string;
  choices: [string, string][];
  selected: string | null | string[];
  onPick: (value: string) => void;
  idPrefix: string;
  error?: string;
}) {
  const labelId = useId();
  const errorId = useId();
  return (
    <div
      id={id}
      role="group"
      aria-labelledby={labelId}
      aria-describedby={error ? errorId : undefined}
      className={styles.choices}
      data-el={`${idPrefix}-GROUP`}
    >
      <p id={labelId} className={styles.label}>
        {label}
      </p>
      {error ? (
        <p id={errorId} className={styles.error}>
          {error}
        </p>
      ) : null}
      <div className={styles.chipRow}>
        {choices.map(([value, text]) => (
          <Chip
            key={value}
            pressed={Array.isArray(selected) ? selected.includes(value) : selected === value}
            onPressedChange={() => onPick(value)}
            dataEl={`${idPrefix}-${value.toUpperCase()}`}
          >
            {text}
          </Chip>
        ))}
      </div>
    </div>
  );
}

/** The card of one step: heading, the summary of problems, the fields, then Back and the one primary button. */
export function StepFrame({
  title,
  errors,
  summaryRef,
  onNext,
  onBack,
  nextLabel,
  footerText,
  busy,
  dataEl,
  secondary,
  children,
}: {
  title: string;
  errors: FieldError[];
  summaryRef?: Ref<HTMLDivElement>;
  onNext: (viaKeyboard: boolean) => void;
  onBack?: () => void;
  nextLabel: string;
  footerText?: string;
  /** The primary button is waiting for an answer. */
  busy?: boolean;
  dataEl?: string;
  /** A second action beside the primary one. */
  secondary?: ReactNode;
  children: ReactNode;
}) {
  const headingId = useId();
  // A press of the button has a click with a count; Enter in a field submits with none, so that is the keyboard.
  const pressed = useRef(false);
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const viaKeyboard = !pressed.current;
    pressed.current = false;
    onNext(viaKeyboard);
  }
  return (
    <form noValidate onSubmit={submit} className={styles.form}>
      <div role="group" aria-labelledby={headingId} className={styles.card}>
        <h1 id={headingId} className={styles.heading}>
          {title}
        </h1>
        <ErrorSummary errors={errors} summaryRef={summaryRef} />
        {children}
        <div className={styles.footer}>
          {onBack ? (
            <button type="button" className={styles.back} onClick={onBack}>
              Back
            </button>
          ) : (
            <p className={styles.footerText}>{footerText}</p>
          )}
          <div className={styles.actions}>
            {secondary}
            <Button
              variant="primary"
              type="submit"
              busy={busy}
              dataEl={dataEl}
              onClick={(event) => {
                pressed.current = event.detail > 0;
              }}
            >
              {nextLabel}
            </Button>
          </div>
        </div>
      </div>
    </form>
  );
}

export function StepService({ values, set, errors, summaryRef, onNext }: StepProps) {
  const errorFor = (field: string) => errors.find((error) => error.field === field)?.message;
  return (
    <StepFrame
      title="The service"
      errors={errors}
      summaryRef={summaryRef}
      onNext={onNext}
      nextLabel="Next: who reports"
      footerText="You can change any of this later"
    >
      <Field id="lead-add-name" label="Service name" error={errorFor('lead-add-name')}>
        {(props) => <input {...props} value={values.name} onChange={(e) => set('name', e.target.value)} />}
      </Field>
      <ChoiceGroup
        id="lead-add-category"
        label="Category"
        choices={CATEGORIES}
        selected={values.category}
        onPick={(value) => set('category', value)}
        idPrefix="LEAD-ADD-CATEGORY"
        error={errorFor('lead-add-category')}
      />
      <ChoiceGroup
        id="lead-add-measure"
        label="What is counted"
        choices={MEASURES}
        selected={values.measure}
        onPick={(value) => set('measure', value)}
        idPrefix="LEAD-ADD-MEASURE"
        error={errorFor('lead-add-measure')}
      />
      <div className={styles.row}>
        <Field
          id="lead-add-unit"
          label="Unit label"
          hint="For example referrals in the next 2 hrs"
          error={errorFor('lead-add-unit')}
        >
          {(props) => <input {...props} value={values.unitLabel} onChange={(e) => set('unitLabel', e.target.value)} />}
        </Field>
        <Field id="lead-add-established" label="Established" error={errorFor('lead-add-established')}>
          {(props) => (
            <input
              {...props}
              inputMode="numeric"
              value={values.establishedCapacity}
              onChange={(e) => set('establishedCapacity', e.target.value)}
            />
          )}
        </Field>
        <Field id="lead-add-usual-min" label="Usual low" error={errorFor('lead-add-usual-min')}>
          {(props) => (
            <input {...props} inputMode="numeric" value={values.usualMin} onChange={(e) => set('usualMin', e.target.value)} />
          )}
        </Field>
        <Field id="lead-add-usual-max" label="Usual high" error={errorFor('lead-add-usual-max')}>
          {(props) => (
            <input {...props} inputMode="numeric" value={values.usualMax} onChange={(e) => set('usualMax', e.target.value)} />
          )}
        </Field>
      </div>
      <p className={styles.note}>Accepts referrals every day, from the From time to the To time.</p>
      <div className={styles.row}>
        <Field id="lead-add-from" label="From" error={errorFor('lead-add-from')}>
          {(props) => (
            <input {...props} placeholder="08:00" value={values.availableFrom} onChange={(e) => set('availableFrom', e.target.value)} />
          )}
        </Field>
        <Field id="lead-add-to" label="To" error={errorFor('lead-add-to')}>
          {(props) => (
            <input {...props} placeholder="20:00" value={values.availableTo} onChange={(e) => set('availableTo', e.target.value)} />
          )}
        </Field>
      </div>
    </StepFrame>
  );
}
