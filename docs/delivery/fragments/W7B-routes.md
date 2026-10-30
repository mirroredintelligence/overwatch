# W7B routes: what the front-end bundles can call (registration, criteria, lead)

Every route below is on the back end's root (not under `/fhir` unless shown), answers JSON in
camelCase with `Cache-Control: no-store`, and takes the tenant from the verified token (or, for the
four sign-in routes, from the request Host). A role a route does not take is the non-revealing 404;
the platform operator's token is a 401. A write needs an `Idempotency-Key` (400 when missing). A
body that names a tenant, a role or a person is a 400 on the sign-in routes. Sample values.

## Registration sign-in (A2): no token, tenant = Host

| Route | Body | Answer |
|---|---|---|
| `POST /identity/invitation` | `{"invitation": "<link token>"}` | `200 {"state":"open","serviceName","numberEnding" (last 3 digits),"expiresAt"}`; `200 {"state":"expired"}` or `{"state":"used"}`; unknown or malformed link: the one `404` |
| `POST /identity/registration/code` | `{"invitation"}` | `202 {"accepted":true,"resendAfterSeconds":60}` (nothing says whether a code was sent); a link that is not open: `404` |
| `POST /identity/registration/session` | `{"invitation" \| "mobile", "code", "deviceId"}` (exactly one of invitation and mobile) | `200 {"token","expiresAt","role":"reporter"}` plus `"registrationId","serviceId","serviceName"` for an invitation; wrong code `400 "That code is not right"`; five wrong tries or lapsed `400 "Ask for a new code"`; a refused device `409`; an unknown or dead invitation `404` |
| `POST /identity/session-token` | `{"sessionId"}` (a live PIN session from `/identity/pin/verify`) | `200 {"token","expiresAt","role"}` (30 minutes); unknown, ended or signed-out session: `404` |

For the reporter app (W7C): after `POST /identity/pin/verify` the BFF sends the `sessionId` to
`POST /identity/session-token` and uses the token it gets as the bearer for the `/reporter/...`
routes (the issue of that token was left to this bundle by W7C). The registration flow's
invitation lookup and code request here are the registration sign-in; W7C's `GET /invitations/{token}`
and `/identity/invitations/{token}/code` are the reporter set-up. Both run the same machinery.

The token is a back-end token (`Authorization: Bearer`): role `reporter`, `sub` = the invited
person (the invitation's, or the holder of the number), `services` = the services that person holds
a reporter post for, `device` = the device the code was checked on, tenant = the Host's, epoch = the
tenant's. Registration token: 2 hours. The BFF keeps no signing secret.

## Registration, applicant (role `reporter`, own registration only)

| Route | Answer |
|---|---|
| `GET /registrations/{id}/record` | `{registrationId,status,serviceId,serviceName,submittedAt,lastModified,invitationExpiresAt,note,noteFrom,steps:{organisation,location,service,reporting,api}}`; each step `{state:"complete"\|"needs-attention"\|"not-started", values:{camelCase}, problems:[{field,message}]}`. The reporting step has `contactMobileEnding` (3 digits) and `hasContactEmail`, never a number or address. The api step is optional. |
| `GET /my/registrations` | `{registrations:[{registrationId,serviceId,serviceName,status,submittedAt}]}` |
| `GET /registrations/{id}/status` | `{registrationId,status,serviceName,submittedAt,note,noteFrom,reason,firstPromptAt,reviewRequestedAt,testSentAt,details:{spoaPhone,criteriaOwner,reportingPhoneEnding}}`. `note` is for needs-changes, `reason` for not-approved. |
| `POST /registrations/{id}/test-notification` (also the lead) | `{sentAt,channel}`; `409` inside a minute or before submission |
| `POST /registrations/{id}/review-request` | `{requestedAt}`; `409` unless submitted or in review |
| `POST /registrations/{id}/confirm-details` | `{status:"live",confirmedAt}`; `409` unless a re-check is due (reverify) |
| `GET /addresses?postcode=` | `{addresses:[{id,label}]}` at most 20 (id is the UPRN, label "line, town"); `400` for a postcode that is not one; `503` when the lookup cannot answer |
| `PUT /fhir/Task/{id}/$draft` | as before, plus body `"partial": true` for Save draft: a part-filled step is saved and the answer is `200` with `"incomplete":[{field,message}]`. `open24h` is accepted. `fixedSite` (location) and `wanted` (api) are still needed. |
| `POST /fhir/Task/{id}/$callback` | `spokeToRole` is optional; needed only when the result is `confirmed` |

## Registration, shift lead

| Route | Answer |
|---|---|
| `GET /registrations?tab=` | `{tab,counts:{waiting,"sent-back",approved,live,"not-approved"},tabs:[{key,label,count}],registrations:[{registrationId,serviceId,serviceName,category,status,submittedAt,registeredBy:{role,contactName},reviewRequestedAt}]}`; default tab `waiting`; oldest submission first; bad tab `400` |
| `GET /registrations/{id}/overview` | `{registrationId,status,serviceId,serviceName,category,checks:[{name,passed,ok,message,explainedNote}],automaticOk,callbackConfirmed,scope,criteriaApproved,missing,registeredBy:{role,contactName,organisationName},applicantNumbers:[{label,ending}],callBack:{numberToCall:null,directoryName,pathwayName}}`; `409` for a registration not yet submitted |
| `GET /registrations/{id}/decision` | `{registrationId,status,missing,approvals:[{key,label,done}],canApprove,test:{sentAt,channel},timeline:[{event,at}]}` |
| `POST /fhir/Task/{id}/$start-review` | `Task` in `in-review` |
| `POST /fhir/Task/{id}/$explain-check` | Parameters `check`, `note` (at most 500); `Parameters {automaticOk}` |

## Criteria (roles `owner`, `clinical`, `lead`; an owner only for a service they hold the owner post of)

| Route | Answer |
|---|---|
| `GET /criteria/{serviceId}` | `{serviceId,serviceName,current:{id,version,status,reviewBy,ageMin,ageMax,accepts:[{code,label}],excludes,districts,changedOn,authorRole},draft:null\|{...,changeReason},pending:null\|{id,version,changeReason,changedOn},overdue,overdueSince,shiftLead:null\|{label,phone},isOwner}`. `draft` is a version the approver sent back; `pending` is waiting for approval. |
| `GET /criteria/{serviceId}/pending` | `{criteriaId,serviceId,serviceName,version,status,changeReason,authorRole,isAuthor,reviewMonths,changedOn,criteria:{...},changes:[{field,label,before,after,words}]}`; `404` when none is waiting. `criteriaId` is the id `$approve` and `$send-back` take. |
| `GET /fhir/Basic?subject=HealthcareService/{id}` | each entry also has `changedOn` and `authorRole` (null for a version stored before they were kept) |

## Shift lead (role `lead`)

| Route | Answer |
|---|---|
| `GET /lead/overview` | `{chasing:[{serviceId,name,dueAt,overdueMinutes,lastValueText,ladder:[{step:"prompt"\|"reminder"\|"phone-task"\|"escalate",at,done}]}],gettingOld:[{serviceId,name,reportedAt,nextDueAt,status}],covering:[{serviceId,name,numberEnding (4 digits, "----" when not kept),until}],counts:{accepting,limited,notAccepting,overCapacity,notUpdated},reportingToday}` |
| `POST /lead/services/{id}/remind` | `{reminded:true}`; `409` when no reminder is waiting |
| `POST /lead/services/{id}/test-prompt` | optional `{"channel":"text"\|"email"\|"push"}`; `{channel,numberEnding}`; `409` inside a minute; `400` when no contact is held for the channel |
| `GET /lead/services/{id}/suspension` | `{suspended,since,reason,expiredRequests,registerNumber}` (the last four are null when not suspended; `expiredRequests` null for a suspension made before it was kept) |
| `GET /lead/reporters[?service=]` | `{reporters:[{serviceId,serviceName,roleId,role,channel,numberEnding (4),coveredUntil}]}`; `roleId` is what `$change-number` and `$remove` take |
| `GET /lead/phones` | `{phones:[{phoneEnding (3),role,services:[{id,name}],channel,lastSeen (ISO or null)}]}` |
| `GET /lead/invitations` | `{items:[{id,serviceName,role,steps:{invited,numberChecked,channelChosen,installed,notificationsOn,pinSet,firstReport},invitedAt,lastSeen,firstReportAt}]}` |
| `POST /lead/invitations/{id}/resend` | `{invitationId,registrationId,expiresAt}`; `409` once the applicant has begun |
| `POST /lead/invitations/{id}/switch-to-text` | `{channel:"text"}`; `409` when no mobile number is held |
| `GET /admin/report-flags?status=open\|closed` | the same FHIR `Bundle` of `Flag`; a closed flag has `status:"inactive"`, `period.end` and `outcome` (`checked` or `accepted`) |
