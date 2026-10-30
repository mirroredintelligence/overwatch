'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useId, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { CodeEntry } from '@/components/forms/CodeEntry';
import styles from './register.module.css';

// Self-registration sign-in (W23, DEC-900 to DEC-902, artboard RegisterFlow1 panels 1 and 2). The
// invitation says whose number the code goes to: the page reads the link, shows the last three digits
// of that number, asks for a code and checks it. The applicant types no number, and the browser holds
// only the three digits. The invitation token is handed in by the page and is never shown.

export type SignInFormProps = {
  /** The invitation token from the page's ?invite= query. Sent to the BFF, never shown. */
  inviteToken?: string;
};

type Invitation =
  | { kind: 'loading' }
  | { kind: 'open'; numberEnding: string }
  | { kind: 'closed'; message: string }
  | { kind: 'unavailable' };
type Stage = 'invitation' | 'code';

const NOT_AN_INVITATION = 'We could not find an invitation for this link. Ask the shift lead to check your invitation.';
const EXPIRED = 'This invitation has expired. Ask the shift lead for a new one.';
const USED = 'This invitation has already been used. Ask the shift lead for a new one.';
const SEND_FAILED = 'We could not send a code. Try again.';
const THROTTLED = 'Too many attempts. Try again later.';
const CHECK_FAILED = 'We could not check the code. Try again.';
const UNAVAILABLE = 'Sign-in is not available right now. Try again shortly.';
const WRONG = 'That code is not right. Check it and try again.';
const EXPIRED_CODE = 'That code has expired. Ask for a new code.';
const NO_INVITATION = 'We could not find an invitation for this number. Ask the shift lead to check it.';
const DEVICE_REFUSED = 'This phone cannot be set up with this code. Start again on this phone.';

async function readJson(response: Response): Promise<Record<string, unknown>> {
  try {
    const parsed = (await response.json()) as unknown;
    return typeof parsed === 'object' && parsed !== null ? (parsed as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

const JSON_POST = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
  cache: 'no-store',
  credentials: 'same-origin',
});

export function SignInForm({ inviteToken }: SignInFormProps) {
  const router = useRouter();
  const formId = useId();
  // No invitation in the link is known at once; with one, the page reads it before it offers a code.
  const [invitation, setInvitation] = useState<Invitation>(() =>
    inviteToken === undefined ? { kind: 'closed', message: NOT_AN_INVITATION } : { kind: 'loading' },
  );
  const [stage, setStage] = useState<Stage>('invitation');
  const [ending, setEnding] = useState<string>('');
  const [notice, setNotice] = useState<string | null>(null);
  const [codeError, setCodeError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (inviteToken === undefined) return undefined;
    let live = true;
    (async () => {
      try {
        const response = await fetch('/api/bff/identity/invitation', JSON_POST({ inviteToken }));
        const body = await readJson(response);
        if (!live) return;
        if (response.status === 404) return setInvitation({ kind: 'closed', message: NOT_AN_INVITATION });
        if (response.status !== 200) return setInvitation({ kind: 'unavailable' });
        if (body.state === 'expired') return setInvitation({ kind: 'closed', message: EXPIRED });
        if (body.state === 'used') return setInvitation({ kind: 'closed', message: USED });
        if (body.state === 'open' && typeof body.numberEnding === 'string') {
          return setInvitation({ kind: 'open', numberEnding: body.numberEnding });
        }
        setInvitation({ kind: 'unavailable' });
      } catch {
        if (live) setInvitation({ kind: 'unavailable' });
      }
    })();
    return () => {
      live = false;
    };
  }, [inviteToken]);

  async function requestCode(): Promise<boolean> {
    setBusy(true);
    setNotice(null);
    let response: Response;
    try {
      response = await fetch('/api/bff/identity/code', JSON_POST({ purpose: 'registration', inviteToken }));
    } catch {
      setBusy(false);
      setNotice(SEND_FAILED);
      return false;
    }
    setBusy(false);
    if (response.status === 202) return true;
    setNotice(response.status === 429 ? THROTTLED : SEND_FAILED);
    return false;
  }

  async function sendCode() {
    if (invitation.kind !== 'open') return;
    setEnding(invitation.numberEnding);
    if (await requestCode()) {
      setCodeError(null);
      setStage('code');
    }
  }

  async function checkCode(code: string) {
    setBusy(true);
    setCodeError(null);
    let response: Response;
    try {
      response = await fetch('/api/bff/identity/code/verify', JSON_POST({ code }));
    } catch {
      setBusy(false);
      setCodeError(CHECK_FAILED);
      return;
    }
    const body = await readJson(response);
    if (response.status === 200) {
      if (typeof body.registrationId === 'string') {
        router.push(`/register/${encodeURIComponent(body.registrationId)}/start`);
        return;
      }
      setBusy(false);
      setCodeError(CHECK_FAILED);
      return;
    }
    setBusy(false);
    switch (response.status) {
      case 400:
        setCodeError(body.code === 'wrong-code' ? WRONG : CHECK_FAILED);
        return;
      case 410:
        setCodeError(EXPIRED_CODE);
        return;
      case 429:
        setCodeError(THROTTLED);
        return;
      case 403:
        setCodeError(NO_INVITATION);
        return;
      case 409:
        setCodeError(DEVICE_REFUSED);
        return;
      default:
        setCodeError(CHECK_FAILED);
    }
  }

  if (stage === 'code') {
    return (
      <div className={styles.stack}>
        <CodeEntry
          ending={ending}
          error={codeError}
          busy={busy}
          onCheck={(code) => void checkCode(code)}
          onResend={() => void requestCode()}
        />
        {notice !== null ? <p className={styles.notice} role="status">{notice}</p> : null}
      </div>
    );
  }

  if (invitation.kind === 'loading') {
    return <p className={styles.text} role="status">Checking your invitation.</p>;
  }
  if (invitation.kind === 'closed') {
    return <p className={styles.notice} role="status">{invitation.message}</p>;
  }
  if (invitation.kind === 'unavailable') {
    return <p className={styles.notice} role="status">{UNAVAILABLE}</p>;
  }

  return (
    <form
      id={formId}
      className={styles.stack}
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        void sendCode();
      }}
    >
      <p className={styles.text}>
        We will text a code to the number your invitation was sent to: 07xxx xxx{invitation.numberEnding}.
      </p>
      <Button variant="primary" type="submit" busy={busy} dataEl="REG-SIGNIN-SEND-BTN">
        Send code
      </Button>
      {notice !== null ? <p className={styles.notice} role="status">{notice}</p> : null}
      <p className={styles.note}>You need an invitation from the shift lead to register. Check your texts or email for the link.</p>
      <p className={styles.note}>Having trouble? Ask the shift lead to check your invitation.</p>
    </form>
  );
}
