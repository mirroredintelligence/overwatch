'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { signOutLocal } from '@/lib/session/signOut';

// Sign out: ends the session, wipes the device and goes to the sign-in page (lib/session/signOut.ts, or the
// operator console's own). A sign-out that could not end the session says so and stays, so a person never
// leaves a shared workstation believing they are signed out when they are not.

export type SignOutFn = () => Promise<{ signedOut: boolean }>;

export function SignOutButton({ signOut = signOutLocal }: { signOut?: SignOutFn }) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  async function run() {
    if (busy) return;
    setBusy(true);
    setFailed(false);
    const result = await signOut();
    setBusy(false);
    if (!result.signedOut) setFailed(true);
  }
  return (
    <div>
      <Button variant="neutral" busy={busy} onClick={() => void run()} dataEl="SIGN-OUT-BTN">
        Sign out
      </Button>
      {failed ? <p role="alert">We could not sign you out. Try again.</p> : null}
    </div>
  );
}
