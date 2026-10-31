import { EncryptJWT, jwtDecrypt } from 'jose';
import { sessionSecretKey } from '@/lib/auth/session';
import { type LinkAnswered, parseLinkAnswered } from './model';

// The thank-you page's detail (KI-179). The page after a recorded figure shows the service, the figure and
// the time. Its address holds no link token (the link is spent), and the detail is sealed by the BFF, not
// written in the address by the browser: a hand-made address cannot make the page say a figure was
// recorded. Sealed with the BFF's own secret as a short-lived token of its own kind (`typ`), so a session
// cookie is not read as one and one is not read as a session. Nothing here is stored.

const TYPE = 'diucs-link-thanks';
const ENCRYPTION = { alg: 'dir', enc: 'A256GCM', typ: TYPE } as const;
const LIFETIME_SECONDS = 10 * 60;

/** Seals what a recorded figure's answer says. Throws for an answer that is not a whole one, and when there is no secret. */
export async function sealThanks(answered: LinkAnswered, now: Date = new Date()): Promise<string> {
  const whole = parseLinkAnswered(answered);
  const issued = Math.floor(now.getTime() / 1000);
  return new EncryptJWT({ ...whole })
    .setProtectedHeader(ENCRYPTION)
    .setIssuedAt(issued)
    .setExpirationTime(issued + LIFETIME_SECONDS)
    .encrypt(await sessionSecretKey());
}

/** What was sealed, or null for anything that is not a live thank-you detail sealed with this key. Throws only when there is no secret. */
export async function unsealThanks(value: string, now: Date = new Date()): Promise<LinkAnswered | null> {
  if (value === '' || value.length > 4096) return null;
  const key = await sessionSecretKey(); // A missing secret is a fault, not "no detail".
  try {
    const { payload, protectedHeader } = await jwtDecrypt(value, key, {
      currentDate: now,
      contentEncryptionAlgorithms: ['A256GCM'],
      keyManagementAlgorithms: ['dir'],
    });
    if (protectedHeader.typ !== TYPE) return null;
    return parseLinkAnswered(payload);
  } catch {
    return null;
  }
}
