// Red stubs (DEC-010).
export type ServiceValues = {
  name: string;
  category: string | null;
  unitLabel: string;
  measure: string | null;
  establishedCapacity: string;
  usualMin: string;
  usualMax: string;
  cadence: string | null;
  channel: 'text' | 'email';
  mobile: string;
  email: string;
  roleName: string;
  availableFrom: string;
  availableTo: string;
  ageMin: string;
  ageMax: string;
  districts: string;
  accepts: string[];
  excludes: string[];
  reviewBy: string;
};
export type FieldError = { field: string; message: string };
export function blankService(): ServiceValues {
  return {
    name: '', category: null, unitLabel: '', measure: null, establishedCapacity: '', usualMin: '',
    usualMax: '', cadence: null, channel: 'text', mobile: '', email: '', roleName: '', availableFrom: '',
    availableTo: '', ageMin: '', ageMax: '', districts: '', accepts: [], excludes: [], reviewBy: '',
  };
}
export function validateService(values: ServiceValues, now: number): FieldError[] {
  void values;
  void now;
  return [];
}
export function toServiceBody(values: ServiceValues): Record<string, unknown> {
  void values;
  return {};
}
