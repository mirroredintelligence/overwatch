// Stub (red commit): the allow-list is not built yet.
export type ConsoleEvent = {
  kind: string;
  offsetMs: number;
  elementId?: string;
  route?: string;
  outcome?: string;
  durationMs?: number;
  status?: string;
  traceId?: string;
};

export function pickAllowed(event: Record<string, unknown>): ConsoleEvent | null {
  return event as unknown as ConsoleEvent;
}
