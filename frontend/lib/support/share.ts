// The support-code request, checked as the back end checks it (R18, support_access.py). A session id is
// the telemetry session id: 16 to 32 hex characters. Nothing here names a person or an organisation.

export const DEVICE_TYPES = ['phone', 'tablet', 'desktop'] as const;
export const APP_MODES = ['browser', 'installed'] as const;
export type DeviceType = (typeof DEVICE_TYPES)[number];
export type AppMode = (typeof APP_MODES)[number];

const SESSION_ID = /^[a-f0-9]{16,32}$/;
const RELEASE_TEXT = /^\d+\.\d+\.\d+$/;

export function isSessionId(value: unknown): value is string {
  return typeof value === 'string' && SESSION_ID.test(value);
}

export type CodeRequest = { sessionId: string; deviceType: DeviceType; appMode: AppMode; release: string };

export function checkCodeRequest(input: unknown): CodeRequest | null {
  if (typeof input !== 'object' || input === null) return null;
  const source = input as Record<string, unknown>;
  const { sessionId, deviceType, appMode, release } = source;
  if (!isSessionId(sessionId)) return null;
  if (typeof deviceType !== 'string' || !(DEVICE_TYPES as readonly string[]).includes(deviceType)) return null;
  if (typeof appMode !== 'string' || !(APP_MODES as readonly string[]).includes(appMode)) return null;
  if (typeof release !== 'string' || !RELEASE_TEXT.test(release)) return null;
  return { sessionId, deviceType: deviceType as DeviceType, appMode: appMode as AppMode, release };
}

/** The role a person sees for who opened the session. Only support opens a session, so anything else is shown as support. */
export function roleLabel(role: string): string {
  void role;
  return 'Support';
}
