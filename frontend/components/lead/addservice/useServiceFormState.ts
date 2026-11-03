import { useCallback, useState } from 'react';
import { blankService, validateService, type FieldError, type ServiceValues } from '@/lib/lead/serviceForm';

// The one form state the steps of "Add a service" share (LDR-03). It lives in the page's memory only: nothing is
// stored in the browser, so a reload starts the form again. The checks are lib/lead/serviceForm.ts's, run for the
// fields of one step at a time ("Next" checks its own step; the last step's Save checks them all).

/** The steps built so far; LDR-04 adds Check and Added. */
export const STEP_COUNT = 3;

// The fields (their ids, as validateService names them) of steps 1 and 2; every other field is on step 3.
const STEP_ONE = [
  'lead-add-name',
  'lead-add-category',
  'lead-add-unit',
  'lead-add-measure',
  'lead-add-established',
  'lead-add-usual-min',
  'lead-add-usual-max',
  'lead-add-from',
  'lead-add-to',
];
const STEP_TWO = ['lead-add-cadence', 'lead-add-mobile', 'lead-add-email', 'lead-add-role'];

/** The step (from 0) a field is on. */
export function stepOfField(field: string): number {
  if (STEP_ONE.includes(field)) return 0;
  if (STEP_TWO.includes(field)) return 1;
  return 2;
}

export function useServiceFormState() {
  const [values, setValues] = useState<ServiceValues>(blankService);
  const [errors, setErrors] = useState<FieldError[]>([]);

  const set = useCallback(<K extends keyof ServiceValues>(key: K, value: ServiceValues[K]) => {
    setValues((previous) => ({ ...previous, [key]: value }));
  }, []);

  const toggle = useCallback((key: 'accepts' | 'excludes', value: string) => {
    setValues((previous) => ({
      ...previous,
      [key]: previous[key].includes(value) ? previous[key].filter((item) => item !== value) : [...previous[key], value],
    }));
  }, []);

  /** Checks the fields of one step (from 0), shows the problems and returns them. */
  const check = useCallback(
    (step: number): FieldError[] => {
      const found = validateService(values, Date.now()).filter((error) => stepOfField(error.field) === step);
      setErrors(found);
      return found;
    },
    [values],
  );

  /** Checks every field. Shows the problems of the earliest step that has any and returns that step, or null. */
  const checkAll = useCallback((): number | null => {
    const all = validateService(values, Date.now());
    if (all.length === 0) {
      setErrors([]);
      return null;
    }
    const first = Math.min(...all.map((error) => stepOfField(error.field)));
    setErrors(all.filter((error) => stepOfField(error.field) === first));
    return first;
  }, [values]);

  const clearErrors = useCallback(() => setErrors([]), []);

  return { values, errors, set, toggle, check, checkAll, clearErrors };
}
