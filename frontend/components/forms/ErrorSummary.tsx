// Red stub (DEC-010).
export type FieldError = { field: string; message: string };
export function ErrorSummary({ errors }: { errors: FieldError[] }) {
  void errors;
  return null;
}
