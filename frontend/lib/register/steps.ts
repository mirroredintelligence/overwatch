import { STEP_NAMES, type StepName } from './types';

/** True for a step name the registration has (organisation, location, service, reporting, api). */
export function isStepName(value: string): value is StepName {
  return (STEP_NAMES as readonly string[]).includes(value);
}
