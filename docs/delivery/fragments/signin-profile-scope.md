# Sign-in asks for the `profile` scope as well as `openid` (pilot finding, 31 October 2026)

Number for the orchestrator to assign: SI-D1. This changes the sign-in flow decision that says `scope=openid` only ("no name, email or profile is asked for, so none arrives").

## What was seen

On the pilot, every staff and operator sign-in passed the Microsoft login and was then refused by the web app with `bad-claims`.
The log named the claims the ID token carried: `aio, aud, exp, iat, iss, nbf, nonce, rh, sub, tid, uti, ver`. There was no
`oid`. `verifyIdToken` requires `tid` and `oid` (the back end keys every person on the pair), so it refused.

## Cause

With the scope `openid` alone, Microsoft Entra ID leaves `oid` out of the ID token. It is included when `profile` is asked for.

## Decision (taken under the delegation to decide design questions; the owner can overrule)

The authorize request asks for `openid profile`. `frontend/lib/auth/oidc.ts` and its test changed; nothing else.

## What this does to the "no name or email" promise

The token now also carries `name` and `preferred_username` (usually the email address). They are not read, stored, sent to the
back end or logged: `verifyIdToken` reads only `tid`, `oid`, `iss` and `nonce`. The promise changes from "none arrives" to
"none is used". Hazard to record: a future change that reads those claims would be reading personal data the earlier decision
said never arrived.

## Alternatives not taken

- Key people on `sub` instead of `oid`: `sub` is different for each app registration, and tenant administrators know a person by
  `oid`, so every provisioning step and the existing records would have to change.
- An optional claim in the app registration: `oid` is not offered as one for ID tokens.

## Revisit if

The owner or the information governance lead wants the earlier promise back: the cost is changing the key from `oid` to `sub`.
