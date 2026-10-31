import { cookies } from 'next/headers';
import { exchangeCode, loadOperatorEntraConfig, newTransaction, authorizeUrl, SignInRefused, verifyIdToken } from '@/lib/auth/oidc';
import { moveOn, nextFrom, see, sealTransaction, TRANSACTION_SECONDS, transactionCookie, unsealTransaction } from '@/lib/auth/flow';
import { normaliseHost, requestHost } from '@/lib/auth/host';
import { readRequestCookie } from '@/lib/auth/session';
import { hostOf } from '@/lib/links/server';
import { safeOperatorNext } from './access';
import { exchangeOperatorToken } from './exchange';
import { createOperatorSession } from './session';

// The two halves of the operator console's sign-in (TEN-083): start (send the browser to the operator's
// directory) and complete (the browser comes back with a code). The same authorisation code flow with PKCE
// as the staff sign-in, with these differences, each of which keeps the operator door apart from a tenant's:
//
//   - its own app registration and directory (`OPERATOR_ENTRA_*`, `DIUCS_OPERATOR_PUBLIC_URL`); it falls
//     back to none of the staff sign-in's settings, and a missing one fails the request that needs it;
//   - it serves only on the console's own host (the host of `DIUCS_OPERATOR_PUBLIC_URL`): a request on a
//     tenant's host makes no transaction and no session;
//   - a transaction cookie of its own (name, path, sealing purpose), so one sign-in cannot complete the other;
//   - the result is an OPERATOR session: the role and account reference the back end's operator exchange
//     gave, no tenant, in a cookie of its own.
//
// Nothing here logs a token, code or claim; a refusal is a fixed word.

export const OPERATOR_TRANSACTION_COOKIE = 'diucs_op_oidc';
const TRANSACTION_PATH = '/api/bff/platform/auth';
const PURPOSE = 'diucs-operator-sign-in';
const FAILED = '/operator/sign-in?error=failed';
const NO_ACCESS = '/operator/sign-in?error=no-access';
const CODE_MAX_LENGTH = 2048;

function note(reason: string): void {
  console.warn(`operator sign-in refused: ${reason}`);
}

function onConsoleHost(request: Request, publicUrl: string): boolean {
  const own = normaliseHost(new URL(publicUrl).host);
  const host = requestHost(request);
  return own !== null && host !== null && own === host;
}

/** POST: the browser is sent to the operator's directory. Reads `next` from the form and nothing else from the request. */
export async function startOperatorSignIn(request: Request): Promise<Response> {
  try {
    const config = loadOperatorEntraConfig();
    if (!onConsoleHost(request, config.publicUrl)) throw new SignInRefused('transaction');
    const transaction = newTransaction(await nextFrom(request));
    const sealed = await sealTransaction(transaction, new Date(), PURPOSE);
    const store = await cookies();
    store.set(OPERATOR_TRANSACTION_COOKIE, sealed, transactionCookie(TRANSACTION_SECONDS, TRANSACTION_PATH));
    return see(authorizeUrl(config, transaction).toString());
  } catch {
    note('could not start');
    return see(FAILED);
  }
}

/** GET: the browser is back from the directory. Checks everything, then creates the operator's own session. */
export async function completeOperatorSignIn(request: Request): Promise<Response> {
  try {
    const config = loadOperatorEntraConfig();
    const store = await cookies();
    const now = new Date();
    // The transaction is single-use: gone from the browser whatever happens next.
    store.set(OPERATOR_TRANSACTION_COOKIE, '', transactionCookie(0, TRANSACTION_PATH));
    if (!onConsoleHost(request, config.publicUrl)) throw new SignInRefused('transaction');

    const transaction = await unsealTransaction(readRequestCookie(request, OPERATOR_TRANSACTION_COOKIE) ?? '', now, PURPOSE);
    if (!transaction) throw new SignInRefused('transaction');

    const query = new URL(request.url).searchParams;
    if (query.has('error')) throw new SignInRefused('provider-error');
    const state = query.get('state');
    const code = query.get('code');
    if (state !== transaction.state) throw new SignInRefused('state');
    if (!code || code.length > CODE_MAX_LENGTH) throw new SignInRefused('state');

    const idToken = await exchangeCode(config, code, transaction);
    await verifyIdToken(config, idToken, transaction.nonce, now);

    // The back end signs the token and says the role; it takes no tenant for an operator.
    const result = await exchangeOperatorToken(idToken, hostOf(request), now);
    if (result.kind === 'refused') return see(NO_ACCESS);
    const { grant } = result;
    const host = requestHost(request);
    if (host === null) throw new SignInRefused('exchange-answer');
    await createOperatorSession({ role: grant.role, host, accountRef: grant.sub, backendToken: grant.token, expiresAt: grant.expiresAt });
    return moveOn(safeOperatorNext(transaction.next, grant.role));
  } catch (error) {
    if (error instanceof SignInRefused) {
      note(error.reason);
      return see(FAILED);
    }
    note('fault');
    return see(FAILED);
  }
}
