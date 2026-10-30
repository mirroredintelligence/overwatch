import { getSession } from '@/lib/auth/session';
import { TelemetryMount } from '@/components/telemetry/TelemetryMount';

// Server side of the telemetry mount (W9F): the browser measures only for a signed-in person, whose
// role the sealed session names. A signed-out page, a session on another host or a session that has
// ended measures nothing, and the ingest would answer 401 to it anyway.

export async function Telemetry() {
  const session = await getSession();
  return session === null ? null : <TelemetryMount role={session.role} />;
}
