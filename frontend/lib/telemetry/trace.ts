// Trace context for the browser (O02). Stub for the red commit.

export const TRACEPARENT_PATTERN = /^00-[0-9a-f]{32}-[0-9a-f]{16}-01$/;

export function newTraceparent(): string {
  return '';
}

export function beginInteraction(): string {
  return '';
}

export function currentTraceId(): string | null {
  return null;
}

export function setRequestObserver(observer: ((traceId: string) => void) | null): void {
  void observer;
}

export function withTraceparent(init: RequestInit = {}): RequestInit {
  return init;
}
