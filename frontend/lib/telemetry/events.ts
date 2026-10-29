// Browser telemetry (O02). Stub for the red commit: nothing is recorded or sent.

export const TELEMETRY_ENDPOINT = '/api/bff/telemetry';
export const BATCH_SIZE = 20;
export const FLUSH_MS = 5000;
export const ALLOWED_ATTRIBUTES: readonly string[] = [];

export type Attributes = Record<string, string | number | boolean>;
export type TelemetryInit = { role: string; release: string };

export function initTelemetry(init: TelemetryInit): void {
  void init;
}

export function stopTelemetry(): void {}

export function track(name: string, attributes: Attributes = {}): void {
  void name;
  void attributes;
}

export function trackPageView(view: { route: string; from?: string; loadType: string }): void {
  void view;
}

export function routeTemplate(pathname: string, params: Record<string, string>): string {
  void params;
  return pathname;
}

export function noteRouteChange(): void {}

export function flush(): void {}
