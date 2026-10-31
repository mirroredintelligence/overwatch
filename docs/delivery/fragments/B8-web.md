# B8-web: the web tier reads its secrets from Key Vault at run time (front end)

Bundle WB15, branch `task/build-WB15` off `integration/build`. Implements DEC-1304 items 1, 3, 4, 5 and 8 for the front end, with the lead's addendum of 2026-10-31 (four secrets, not two). No decision number block was given, so the decisions below are numbered B8W-1 to B8W-8 for the orchestrator to number. Hazards H-840 to H-849 (H-840 to H-846 used).

## Decisions

### B8W-1 The web tier reads four vault secrets and nothing else
`session-secret`, `edge-origin`, `entra-staff-client-secret` (was `ENTRA_CLIENT_SECRET`, `lib/auth/oidc.ts` `loadEntraConfig`) and `entra-operator-client-secret` (was `OPERATOR_ENTRA_CLIENT_SECRET`, `loadOperatorEntraConfig`). A fifth name is refused as not found: the module has a fixed table of the four secrets and the plain variable each one has when there is no vault, so it can never become a general reader. Client ids, directory ids, public URLs and the authority host stay environment settings (none is secret).

### B8W-2 One module, `frontend/lib/secrets/`, server only
`getSecret(name): Promise<string>` (a string: every one of the four is text; `session.ts` turns the session secret into its 32 key bytes). Injectable vault client and clock (`createSecrets({ env, client, createClient, now, warn })`); the shared instance reads `process.env` at each call and builds the Azure client (`@azure/keyvault-secrets` `SecretClient` with `@azure/identity` `DefaultAzureCredential`) on first use only, so a run with no vault never loads the SDK. Packages are exact pins from commit efe3a70 (identity 4.13.3, keyvault-secrets 4.11.2); dependencies were not changed in this bundle. Server-only is enforced as the other server modules are: the ESLint `no-restricted-imports` list (`eslint.config.mjs`) now forbids a component importing `@/lib/secrets`, `@/lib/secrets/*` and `@/lib/auth/oidc` (type imports allowed), with cases in `test/guards/eslint-rules.test.ts`.

### B8W-3 The rules of DEC-1304, as built
Name rule: lower-case letters, digits and single hyphens, at most 127 characters; anything else is `SecretNotFoundError` before the vault is called (`isSecretName`). Cache: 600 s (`DIUCS_SECRET_CACHE_SECONDS`), successes only; a miss, a refusal or an outage is never kept; callers that arrive together share one vault request. Stale-if-error: when a refresh fails and an earlier good value is held, it is served for 3600 s past expiry (`DIUCS_SECRET_STALE_SECONDS`, 0 is strict fail-closed) with a `console.warn` that names the secret only; then the read fails closed. A secret never read has nothing to serve. The two settings must be whole seconds from 0 to 86400, otherwise `SecretConfigurationError` naming the variable. Errors never carry the vault's own text (it is not ours to vouch for) and never a value; the leak test pushes a canary through every path and checks every log call, message, stack, `String`, and JSON form.

### B8W-4 No vault, plain variables as today; a vault with a plain variable refuses to serve
Without `DIUCS_KEY_VAULT_URL` the four plain variables (`SESSION_SECRET`, `DIUCS_EDGE_ORIGIN_SECRET`, `ENTRA_CLIENT_SECRET`, `OPERATOR_ENTRA_CLIENT_SECRET`) work as they always did (local runs, tests, the e2e stand-ins). With it, a process that has any of the four set, even one that is not the secret being read, throws `SecretConfigurationError` at first use naming the variable, never its value. The check runs on every call, so a variable that appears after the first read is caught. An empty variable counts as unset. The vault URL must be `https`. The refusal is at first use, not at start-up: the web tier has no start-up hook (`instrumentation.ts` does not exist) and the first request is the first use.

### B8W-5 Every reader awaits; a missing, unreadable or malformed secret is a fault
`sessionSecretKey()` (and the keys derived from it) is async. Converted: `lib/auth/session.ts`, `csrf.ts`, `flow.ts`, `lib/operator/session.ts`, `csrf.ts`, `lib/register/pending.ts`, `lib/links/csrf.ts`, `thanks.ts`, `lib/screens/cookies.ts`, `lib/fhir/hostCall.ts`, and the three loaders' callers (`lib/auth/flow.ts`, `lib/operator/flow.ts`). `csrfTokenFor`, `verifyCsrfToken`, `checkCsrf` and the operator and renewal equivalents now return promises, and every caller (the BFF seams `withBff`, `withOperatorBff`, the reporter seam, three session routes, the link renew route) awaits them. A secret that is missing, unreadable or not 32 bytes of base64 throws (a 5xx at the BFF seam), with a message that names the secret. Three behaviours changed from a quiet outcome to a fault: `unsealThanks` (was null), `checkRenewCsrf` (was `false`, a 403) and the renew route when there is no secret. The public thank-you page (`app/l/thanks/page.tsx`) catches the `unsealThanks` fault itself and says only thank you (a courtesy detail; see the known issue below).

### B8W-6 `callBackend` and the edge secret
`callBackend` reads `edge-origin` through the module. No vault and no `DIUCS_EDGE_ORIGIN_SECRET`: the Host header, as before (local and test). A vault, with the secret missing or unreadable: a thrown `SecretNotFoundError` or `SecretConfigurationError`, nothing sent and no fall-back to Host (a Host call to the internal API name would be routed to `web`, DEC-1303). A value that is not a header-safe visible-ASCII string is a configuration error (it could inject a header). These errors are not `BackendCallError`, so a route that treats a back end outage as "unavailable" does not treat a set-up fault as one.

### B8W-7 The sign-in routes answer a secret fault with the failed-sign-in page, not a 5xx
`startSignIn`, `completeSignIn` and the operator pair catch every error and send the browser to the failed page with a fixed log word ("could not start", "fault"); that was the behaviour before and it stays: it is a refusal, never a session and never a pass, and the browser needs a page. The fault is not lost: the warning is logged, and the other readers (every BFF call, page and proxy) do throw.

### B8W-8 The proxy runs in Node
Next 16 `proxy.ts` has the Node.js runtime and no other (the `runtime` option is not available there), so it can use the module and the Azure SDK. It already awaited `sessionFromRequest` and `operatorSessionFromRequest`, which now read the secret through the module; nothing moved. No path in the front end runs in the edge runtime.

## Hazards

- **H-840** (HIGH) A secret read fails (vault outage, missing role) and a reader treats it as "no session", "no match" or "no CSRF token", or lets a request through. Control: every reader awaits the module and the error propagates; `lib/secrets/webTier.test.ts` calls all 23 readers with the secret missing, unreadable and malformed and expects each to throw; the routes' tests for missing secrets expect a throw or a refusal, never a pass.
- **H-841** (HIGH) A secret value reaches a log, an error, a response, a prop or the leak canary. Control: errors and warnings name the secret and never the value or the vault's text; the canary is pushed through every failing path of the module in `secrets.test.ts`; the leak-canary suite passes.
- **H-842** (HIGH) A secret left in the environment of a vault-using app is used or is read from the process environment by anything that dumps it. Control: with the vault URL set, any of the four plain variables makes every read throw naming the variable; the pilot's `web` must carry none of them.
- **H-843** (MEDIUM) A vault outage stops the web tier within ten minutes. Control: stale-if-error for 3600 s with a warning that names the secret; `DIUCS_SECRET_STALE_SECONDS=0` is the strict setting; one outage costs one warning per call while stale, never a value.
- **H-844** (MEDIUM) A failed read is cached and keeps a good web app down after the vault returns, or a refresh storm hits the vault. Control: failures are never cached; callers that arrive together share one request; the SDK retry budget is short (2 retries, 2 s cap) because a request is waiting.
- **H-845** (MEDIUM) The edge secret is missing on the pilot and the call goes to the API with `Host` set to a tenant, reaching the wrong app or resolving the wrong tenant. Control: with a vault there is no Host fallback (B8W-6); tests.
- **H-846** (LOW) A client reads a server-only module and the secret code reaches the browser bundle. Control: ESLint `no-restricted-imports` (B8W-2) and the `lib/secrets` module has no `NEXT_PUBLIC` reader; the SDK is imported dynamically on first use.

## Known issues (with triggers)

- The web tier reads the vault at first use, not at start-up, so a mis-set pilot app (a plain variable beside the vault URL, a missing role) shows as 5xx on the first request, not as a failed start. Trigger: the pilot needs a start-up failure to stop a bad revision from taking traffic (add a Next.js `instrumentation.ts` that reads the four secrets, with a health probe).
- The sign-in routes turn a secret fault into the failed-sign-in page (B8W-7), so a vault outage at sign-in looks like a failed sign-in to the person. Trigger: staff report "sign-in failed" with no cause; the log has "staff sign-in refused: fault".
- The public link pages (`GET` and answer routes) and the thank-you page still leave the optional renewal token and the thank-you detail out when the secret cannot be read, and answer 410 or 200 with the state alone (KI-178, KI-179 behaviour kept): the page is true without them and nothing is passed. The renewal itself (`POST .../renew`) is a fault with no secret. Trigger: the closed-link page must show a renew button during a vault outage.
- The session key is derived per request from the cached secret (HKDF each call), as it was from the environment. Trigger: profiling shows the derivations in the request path.
- A rotated secret takes up to 600 s (and the stale window, on an outage) to reach a running replica; sessions sealed under the old value stop opening at that point, so rotation is a sign-out of everyone. Trigger: the first rotation of `session-secret` (needs the previous key kept for unsealing; not built).
- `DefaultAzureCredential` tries its whole chain locally (a developer's login); in Azure `AZURE_CLIENT_ID` names the one user-assigned identity. A web app with no identity assigned takes the full chain's timeout on its first read before failing. Trigger: first deploy of `web`.
- Not run: the real Azure SDK against a vault (no network, no vault here). The default-client test builds the SDK client without a call and checks only that it has `getSecret` and made no `fetch`.

## What the pilot web app needs

Environment (none is secret): `DIUCS_KEY_VAULT_URL` (the vault's `https` address), `AZURE_CLIENT_ID` (the user-assigned identity of `web`), `DIUCS_FHIR_BASE_URL` (`https://api.internal.<env-domain>/fhir`), and the existing non-secret settings: `ENTRA_CLIENT_ID`, `ENTRA_DIRECTORY_ID` (if single-directory), `ENTRA_AUTHORITY_HOST`, `DIUCS_PUBLIC_URL`, `OPERATOR_ENTRA_CLIENT_ID`, `OPERATOR_ENTRA_DIRECTORY_ID`, `DIUCS_OPERATOR_PUBLIC_URL`. Optional: `DIUCS_SECRET_CACHE_SECONDS` (600), `DIUCS_SECRET_STALE_SECONDS` (3600).

Must NOT be set on `web` when `DIUCS_KEY_VAULT_URL` is set: `SESSION_SECRET`, `DIUCS_EDGE_ORIGIN_SECRET`, `ENTRA_CLIENT_SECRET`, `OPERATOR_ENTRA_CLIENT_SECRET` (the app refuses to serve).

Key Vault: the identity of `web` holds Key Vault Secrets User on the vault and nothing else; the vault holds `session-secret` (32 random bytes, base64: 44 characters with one `=`), `edge-origin` (the same value the API reads; visible ASCII only), `entra-staff-client-secret` and `entra-operator-client-secret`. The names are the vault's own names, with no `/` and no `--`.

## Contracts

- `@/lib/secrets`: `getSecret(name)`, `vaultConfigured()`, `createSecrets(options)`, `isSecretName(value)`, `SecretNotFoundError`, `SecretConfigurationError`, `type VaultClient = { getSecret(name): Promise<{ value?: string }> }`. Server only.
- Environment: `DIUCS_KEY_VAULT_URL`, `DIUCS_SECRET_CACHE_SECONDS`, `DIUCS_SECRET_STALE_SECONDS`, `AZURE_CLIENT_ID` (read by the Azure SDK).
- Now async: `sessionSecretKey`, `operatorSealingKey`, `csrfTokenFor`, `verifyCsrfToken`, `checkCsrf`, `operatorCsrfTokenFor`, `verifyOperatorCsrfToken`, `checkOperatorCsrf`, `renewCsrfFor`, `checkRenewCsrf`, `loadEntraConfig`, `loadOperatorEntraConfig`. Test helpers `csrfFor`, `csrfOf`, `preSessionCsrfFor`, `operatorCsrfOf`, `requestPreSession` and `phoneCall` are async too.
- `loadEntraConfig(env)` and `loadOperatorEntraConfig(env)` take the non-secret settings from `env` and the client secret only from the module (a client secret in `env` is ignored).

## Tenant pending

None: the front end holds no graph statement. The tenant for pre-session calls is still the host (DEC-134, DEC-1303).
