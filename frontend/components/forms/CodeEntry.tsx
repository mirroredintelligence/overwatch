// Stub (red commit).

export type CodeEntryProps = {
  /** The full UK mobile. Only its last three digits are ever shown. */
  mobile: string;
  error?: string | null;
  busy?: boolean;
  onCheck: (code: string) => void;
  onResend: () => void;
};

export function CodeEntry(_props: CodeEntryProps) {
  return null;
}
