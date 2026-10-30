// DEC-010 stub (W30 red). The owner's rules: see the implement commit.
import type { NeedCode } from './types';

export const NEED_LABELS: Readonly<Record<NeedCode, string>> = {
  'fall-no-injury': 'Fall, no injury',
  frailty: 'Frailty',
  'wound-care': 'Wound care',
  'iv-therapy': 'IV therapy',
  palliative: 'Palliative',
  dementia: 'Dementia',
  'suspected-fracture': 'Suspected fracture',
  'head-injury-anticoagulants': 'Head injury on anticoagulants',
  'infection-isolation': 'Infection isolation',
};

export function conflictError(_accepts: readonly NeedCode[], _excludes: readonly NeedCode[]): string | null {
  return null;
}
