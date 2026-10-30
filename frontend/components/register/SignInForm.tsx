'use client';

import { useRouter } from 'next/navigation';
import { useId, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { CodeEntry } from '@/components/forms/CodeEntry';
import { TextField } from '@/components/forms/TextField';
import { mobileProblem, normaliseMobile } from '@/lib/register/phone';
import styles from './register.module.css';

// Self-registration sign-in (W23, artboard RegisterFlow1 panels 1 and 2). The applicant gives the
// mobile the invitation was sent to; a text code proves it. The number is held only in this
// component's state while the code is checked, and is never put in the page, a URL or storage.

export type SignInFormProps = {
  /** The invitation token from the page's ?invite= query. Sent to the BFF, never shown. */
  inviteToken?: string;
};

type Stage = { kind: 'number' } | { kind: 'code'; mobile: string };

const NUMBER_EMPTY = 'Enter your mobile number';
const NUMBER_INVALID = 'Enter a UK mobile number, like 07700 900456';
const SEND_FAILED = 'We could not send a code. Try again.';
const THROTTLED = 'Too many attempts. Try again later.';
const CHECK_FAILED = 'We could not check the code. Try again.';

const NO_INVITATION = 'We could not find an invitation for this number. Ask the SPOA shift lead to check it.';

function triesLeft(count: number): string {
  return count === 1 ? '1 try' : `${count} tries`;
}

async function readJson(response: Response): Promise<Record<string, unknown>> {
  try {
    const parsed = (await response.json()) as unknown;
    return typeof parsed === 'object' && parsed !== null ? (parsed as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

export function SignInForm({ inviteToken }: SignInFormProps) {
  const router = useRouter();
  const formId = useId();
  const [stage, setStage] = useState<Stage>({ kind: 'number' });
  const [number, setNumber] = useState('');
  const [numberError, setNumberError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [codeError, setCodeError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function requestCode(mobile: string) {
    setBusy(true);
    setNotice(null);
    let response: Response;
    try {
      response = await fetch('/api/bff/identity/code', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phone: mobile, purpose: 'registration', inviteToken }),
        cache: 'no-store',
        credentials: 'same-origin',
      });
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
    const problem = mobileProblem(number);
    if (problem !== null) {
      setNumberError(problem === 'empty' ? NUMBER_EMPTY : NUMBER_INVALID);
      return;
    }
    const mobile = normaliseMobile(number);
    if (mobile === null) {
      setNumberError(NUMBER_INVALID);
      return;
    }
    setNumberError(null);
    if (await requestCode(mobile)) {
      setNumber('');
      setCodeError(null);
      setStage({ kind: 'code', mobile });
    }
  }

  async function checkCode(mobile: string, code: string) {
    setBusy(true);
    setCodeError(null);
    let response: Response;
    try {
      response = await fetch('/api/bff/identity/code/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phone: mobile, code }),
        cache: 'no-store',
        credentials: 'same-origin',
      });
    } catch {
      setBusy(false);
      setCodeError(CHECK_FAILED);
      return;
    }
    if (response.status === 200) {
      const body = await readJson(response);
      if (typeof body.registrationId === 'string') {
        router.push(`/register/${encodeURIComponent(body.registrationId)}/start`);
        return;
      }
      setBusy(false);
      setCodeError(CHECK_FAILED);
      return;
    }
    setBusy(false);
    const body = await readJson(response);
    switch (response.status) {
      case 400:
        setCodeError(
          typeof body.triesLeft === 'number'
            ? `That code is not right. You have ${triesLeft(body.triesLeft)} left.`
            : 'That code is not right. Check it and try again.',
        );
        return;
      case 410:
        setCodeError('That code has expired. Ask for a new code.');
        return;
      case 429:
        setCodeError('Too many wrong tries. Ask for a new code.');
        return;
      case 403:
        setCodeError(NO_INVITATION);
        return;
      default:
        setCodeError(CHECK_FAILED);
    }
  }

  if (stage.kind === 'code') {
    const { mobile } = stage;
    return (
      <div className={styles.stack}>
        <CodeEntry
          mobile={mobile}
          error={codeError}
          busy={busy}
          onCheck={(code) => void checkCode(mobile, code)}
          onResend={() => void requestCode(mobile)}
        />
        {notice !== null ? <p className={styles.notice} role="status">{notice}</p> : null}
      </div>
    );
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
      <p className={styles.text}>Enter your mobile number. We text you a code to check it is you.</p>
      <TextField
        id="mobile"
        label="Mobile number"
        value={number}
        onChange={setNumber}
        type="tel"
        inputMode="tel"
        autoComplete="tel"
        hint="Use the number your invitation was sent to"
        error={numberError}
        dataEl="REG-SIGNIN-NUMBER-FIELD"
      />
      <Button variant="primary" type="submit" busy={busy} dataEl="REG-SIGNIN-SEND-BTN">
        Send code
      </Button>
      {notice !== null ? <p className={styles.notice} role="status">{notice}</p> : null}
      <p className={styles.note}>You need an invitation from the SPOA shift lead to register. Check your texts or email for the link.</p>
      <p className={styles.note}>Having trouble? Ask the SPOA shift lead to check your invitation.</p>
    </form>
  );
}
