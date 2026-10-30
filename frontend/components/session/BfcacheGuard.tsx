'use client';

import { useEffect } from 'react';
import { installBfcacheGuard } from '@/lib/session/signOut';

// Renders nothing. A page the back-forward cache brings back is shown as it was left, after a
// sign-out too; this reloads it so the server decides whether the person may see it (TEN-050,
// audit D R10). Mounted once, in the root layout.

export function BfcacheGuard({ reload = () => window.location.reload() }: { reload?: () => void }) {
  useEffect(() => installBfcacheGuard(window, reload), [reload]);
  return null;
}
