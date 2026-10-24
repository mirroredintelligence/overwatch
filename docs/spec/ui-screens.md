# DIUCS capacity: UI screens (text extracted from the design canvas)

Source: design canvas 'DIUCS SPOA Capacity: Journeys and UI'. Each section is one artboard. Lines starting [btn] are buttons; [input ...] are fields. '--- script ---' blocks hold the sample data the artboard renders (sample data only).


## Artboard: Journeys

User journeys: reporter and advisor
## {{j.title}}
{{j.sub}}
{{s}}
{{r.label}}
{{c}}

--- script ---
class Component extends DCLogic {
  renderVals() {
    const WHITE = '#FFFFFF', TINT = '#E3F1F8', AMBER = '#FFF1DC';
    const journeys = [
      {
        title: 'Reporter loop by text',
        sub: 'Duty manager or coordinator. The text shows what is recorded and has a link. Confirm or update. No login.',
        stages: ['1 Prompt arrives', '2 Reply', '3 Confirmation', '4 Things change', '5 Report missed', '6 Leave or cover'],
        rows: [
          { label: 'Does', bg: WHITE, cells: [
            'Gets a text at the usual time, sent to the role phone. It shows what is already recorded.',
            'Taps the link and confirms or updates the figure. Or replies Y, or a new number.',
            'Reads the echo and the next update time. Sends the right number if it is not right.',
            'Sends an update outside the schedule when the position changes.',
            'Busy on the ward. Nothing sent.',
            'The named person is away. Cover needs to reply.'
          ] },
          { label: 'Sees', bg: WHITE, cells: [
            'Service, the recorded figure and when, the unit, a deadline. One text segment.',
            'Nothing else to fill in. No free text.',
            'Number, time recorded, time of the next prompt.',
            'The same prompt, at any time, built from the saved service profile.',
            'A reminder after 30 min. Then a phone task goes to the advisor.',
            'The shift lead changes the registered number in one step.'
          ] },
          { label: 'Feels', bg: WHITE, cells: [
            'Mildly interrupted.', 'Quick. Under 10 seconds.', 'Reassured it was received.', 'In control of what the board says.', 'Slightly guilty, not blamed.', 'Relieved nothing breaks.'
          ] },
          { label: 'Risks', bg: AMBER, cells: [
            'F12 reporter fatigue', 'F16 misread reply · F18 spoofing', 'F16 wrong figure', 'F2 capacity changes between reports', 'F14 no report · F3 stale data', 'F9 named person away'
          ] },
          { label: 'Design response', bg: TINT, cells: [
            'Fixed reply words: Y or a number. No STOP, START or HELP.',
            'Range check on every number. Unknown numbers get no reply.',
            'Echo with a timestamp. Y is logged as its own type, capped at two in a row.',
            'Pushed updates refresh the board straight away.',
            'The board shows Not updated, never a confident old number.',
            'Late replies get the current prompt, not silence.'
          ] }
        ]
      },
      {
        title: 'Advisor call flow',
        sub: 'SPOA call advisor. Time-pressured, on the phone, recording in SystmOne.',
        stages: ['1 Call arrives', '2 Capture needs', '3 See options', '4 Check criteria', '5 Hold or phone', '6 Offer to caller', '7 Record outcome'],
        rows: [
          { label: 'Does', bg: WHITE, cells: [
            'Ambulance crew or care home phones. Advisor opens a case.',
            'Taps age band, urgency and needs. Types the postcode while listening.',
            'Reads the services that meet the hard criteria, sorted by travel time.',
            'Opens one service to see what it accepts and does not accept.',
            'Sends a booking request by text and waits for CONFIRMED, or phones to confirm and logs the real position.',
            'Tells the caller the service, the response time and what happens next.',
            'Marks accepted, declined or redirected, and why. Copies the summary to SystmOne.'
          ] },
          { label: 'Sees', bg: WHITE, cells: [
            'An empty case. The wall board stays in view.',
            'Selected chips. No free text and no patient name.',
            'Status shape, number, data age, and reasons for and against. Not ranked.',
            'Criteria version, last reviewed date and an expiry flag.',
            'A pending request, visible to colleagues on the board. Not booked until confirmed.',
            'The confirmed position and how old it is.',
            'One structured summary, ready to paste.'
          ] },
          { label: 'Feels', bg: WHITE, cells: [
            'Alert, short of time.', 'In flow.', 'Confident, or doubtful when data is old.', 'Reassured by clear limits.', 'A little tense.', 'Able to give a clear answer.', 'Finished, not monitored.'
          ] },
          { label: 'Risks', bg: AMBER, cells: [
            'N4 re-keying the same details', 'F4 patient details in free text', 'F1 over-trust · F3 stale data', 'F7 out-of-date criteria', 'F15 double booking · F2 capacity moved', 'F11 wrong-fit service', 'F5 gamed reporting · F10 no audit trail'
          ] },
          { label: 'Design response', bg: TINT, cells: [
            'One tap to open. Nothing to log in to mid-call.',
            'Chips and postcode only. Needs are cleared when the record closes.',
            'Two or more options with reasons. Stale data is labelled in words.',
            'Versioned criteria with an owner and a review date.',
            'Request tap, then I phoned. Unanswered requests expire and prompt a phone call.',
            'Hard exclusions filter. The advisor decides. Clinical advisor one tap away.',
            'Capacity, data age and criteria version saved with the decision.'
          ] }
        ]
      }
    ];
    return { journeys };
  }
}

## Artboard: Journeys2

User journeys: email and booking
## {{j.title}}
{{j.sub}}
{{s}}
{{r.label}}
{{c}}

--- script ---
class Component extends DCLogic {
  renderVals() {
    const WHITE = '#FFFFFF', TINT = '#E3F1F8', AMBER = '#FFF1DC';
    const journeys = [
      {
        title: 'Reporter loop by email',
        sub: 'For services that use email instead of text. One-tap link, no login. Confirm or update.',
        stages: ['1 Email arrives', '2 Open the link', '3 Confirm or update', '4 Thank-you page', '5 Link expired or used', '6 Next prompt'],
        rows: [
          { label: 'Does', bg: WHITE, cells: [
            'Gets an email from DIUCS at the usual time, sent to the role inbox.',
            'Taps the link. A small page opens. No login.',
            'Taps Yes, still 3. Or uses the stepper to send a new number. Or says closed.',
            'Reads the confirmation. Changes it if it is wrong.',
            'Opens an old link, or one that was already used.',
            'Waits for the next email.'
          ] },
          { label: 'Sees', bg: WHITE, cells: [
            'Subject with the service and the deadline. One link. No patient information.',
            'The recorded figure and its age, large buttons, and the usual range.',
            'A big number stepper and one primary button.',
            'The figure, the time recorded, the next update due, and a link to the live board.',
            'A plain page: this link has expired. Send me a new one.',
            'The next due time, from the confirmation page.'
          ] },
          { label: 'Feels', bg: WHITE, cells: [
            'Mildly interrupted.', 'Reassured it is simple.', 'Done in seconds.', 'Confident it was received.', 'Slightly annoyed, not stuck.', 'Nothing to remember.'
          ] },
          { label: 'Risks', bg: AMBER, cells: [
            'F13 delivery and spam folders', 'F18 forwarded or spoofed link', 'F16 wrong figure', 'F2 capacity changes after reporting', 'F14 no report', 'F9 inbox not watched'
          ] },
          { label: 'Design response', bg: TINT, cells: [
            'Role inbox, not a named person. The deadline is in the subject.',
            'Single-use link with a short life, tied to one prompt.',
            'Recorded figure shown with its age. Range check on every number.',
            'Echo with a timestamp. Confirming is capped at two in a row, as for text.',
            'A new link on request. A text reply stays as a fallback.',
            'A missed email triggers the same reminder and phone task as text.'
          ] }
        ]
      },
      {
        title: 'Booking request by text or email',
        sub: 'Advisor asks, the service replies. Not booked until the service confirms.',
        stages: ['1 Advisor requests', '2 Request arrives', '3 Service reads it', '4 Service replies', '5 Advisor sees the result', '6 No reply', '7 Declined'],
        rows: [
          { label: 'Does', bg: WHITE, cells: [
            'Taps Request booking on a service card. The card shows Requested.',
            'The service coordinator gets a text or an email with a reference and no patient name.',
            'Reads the age band, need and urgency. Checks they can take it.',
            'Text: replies CONFIRMED or DECLINE. Email: opens the link, then confirms or declines on the page.',
            'The card turns to Booked. Advisor completes the SystmOne referral and records the outcome.',
            'After 5 min the advisor is prompted to phone. At 10 min the request expires.',
            'Advisor offers another option or phones to discuss.'
          ] },
          { label: 'Sees', bg: WHITE, cells: [
            'A pending count on the board, so colleagues do not double book.',
            'Reference, service, age band, need, urgency and a reply-by time.',
            'The line: referral details follow in SystmOne.',
            'An echo: Booked, with the reference and the time.',
            'Booked, confirmed time, capacity reduced by 1.',
            'The No reply state, a Phone button and Try next option.',
            'Declined, the reason, and a way back to the options.'
          ] },
          { label: 'Feels', bg: WHITE, cells: [
            'Hopeful, short of time.', 'Interrupted, then clear.', 'Weighing it up.', 'Quick, done.', 'Relieved. One more step.', 'Tense, with the caller waiting.', 'Disappointed, not stuck.'
          ] },
          { label: 'Risks', bg: AMBER, cells: [
            'F15 double booking', 'F4 patient details in the message', 'F1 reflex yes', 'F16 reply misread', 'F10 no audit trail', 'The caller waits', 'F5 gamed reporting'
          ] },
          { label: 'Design response', bg: TINT, cells: [
            'Pending is shown apart from available. Not booked until confirmed.',
            'No name and no free text. IG to approve the exact wording.',
            'A decline reason is one tap and optional.',
            'One open request per service. The reply is matched by reference.',
            'Reference, sender number and times are saved with the capacity snapshot.',
            'Phone prompt at 5 min and expiry at 10. Silence is never acceptance.',
            'Decline reasons feed the declined-despite-capacity log.'
          ] }
        ]
      }
    ];
    return { journeys };
  }
}

## Artboard: Journeys3

User journeys: shift lead and clinical advisor
## {{j.title}}
{{j.sub}}
{{s}}
{{r.label}}
{{c}}

--- script ---
class Component extends DCLogic {
  renderVals() {
    const WHITE = '#FFFFFF', TINT = '#E3F1F8', AMBER = '#FFF1DC';
    const WHITE = '#FFFFFF', TINT = '#E3F1F8', AMBER = '#FFF1DC';
    const journeys = [
      {
        title: "Shift lead: a shift",
        sub: "SPOA shift lead. Owns the board, the chasing, registrations and criteria reviews.",
        stages: ["1 Start of shift", "2 Watch the board", "3 Chase a late reporter", "4 Flagged report or alert", "5 Invite, move or suspend", "6 Registrations and criteria", "7 Hand over"],
        rows: [
          { label: "Does", bg: WHITE, cells: [
            "Signs in with the Trust account. Opens the board and the lead page.",
            "Keeps the board in view. Checks counts and who is not updated.",
            "Follows the ladder: reminder sent, advisor phone task, then escalated to them.",
            "Opens a flagged report or an alert. Phones to confirm. Marks it checked.",
            "Sends an invitation, changes a cover number, moves a service, or suspends one.",
            "Works the approval queue: call-back, scope, decision. Sends criteria reminders.",
            "Notes open items for the next lead. Signs out."
          ] },
          { label: "Sees", bg: WHITE, cells: [
            "Who is on duty, open alerts and pending approvals.",
            "Status shapes, data ages, pending counts and system pressure.",
            "The non-responder card with the ladder and the last figure.",
            "Why a report was flagged, and what advisors recorded by phone.",
            "The effects of each action, listed in plain words before it happens.",
            "What each check needs. Approve stays unavailable until all are done.",
            "Open items and recent actions."
          ] },
          { label: "Feels", bg: WHITE, cells: [
            "Ready.",
            "In control.",
            "A little pressed.",
            "Alert and careful.",
            "Confident, one step at a time.",
            "Methodical.",
            "Able to hand over cleanly."
          ] },
          { label: "Risks", bg: AMBER, cells: [
            "F47 lead absent, approvals stall",
            "F3 stale figure looks fresh",
            "F14 no report received",
            "F5 gamed reporting \u00b7 F18 spoofed reporter",
            "F23 lost phone \u00b7 F26 fake service",
            "F25 skipped check \u00b7 F7 old criteria",
            "F10 no audit trail"
          ] },
          { label: "Design response", bg: TINT, cells: [
            "One sign-in. A deputy can cover when the lead is away.",
            "Not updated is a shape and a word. An old figure never looks fresh.",
            "One tap to phone, enter what they said, or switch them to text.",
            "Flags come from rules, never from a person's speed. Resolving is logged.",
            "Every action shows what happens at once. Resume needs a call-back and a reason.",
            "Checks in a fixed order. Two approvals for criteria.",
            "Every action is in the audit record, so handover needs no memory."
          ] }
        ]
      },
      {
        title: "Clinical advisor: a request",
        sub: "Clinical advisor on duty. Gives advice on a case an advisor has escalated.",
        stages: ["1 Go on duty", "2 Alert arrives", "3 Take the request", "4 Review the case", "5 Give advice", "6 Logged, next request", "7 Go off duty"],
        rows: [
          { label: "Does", bg: WHITE, cells: [
            "Signs in with the Trust account. Sets status to Available.",
            "Gets a notification: clinical advice requested, with age band and need.",
            "Opens the queue and takes the request. No one else can.",
            "Reads the case, the scores and what the advisor saw. Phones the advisor if needed.",
            "Chooses advice from a short list and a reason. Adds a short note only if needed.",
            "Sees advice sent and logged. Takes the next request.",
            "Sets Away or signs out. Unfinished requests return to the queue."
          ] },
          { label: "Sees", bg: WHITE, cells: [
            "How many requests wait, and how many clinical advisors are on.",
            "Urgency and waiting time. No postcode in the notification.",
            "The request is now theirs, with a 10-minute timer.",
            "Age band, postcode, needs, scores, options shown and criteria versions.",
            "Structured choices: go ahead, another service, a clinical call, the emergency route.",
            "Confirmation, and that the advice is logged for audit.",
            "Any requests handed back to the queue."
          ] },
          { label: "Feels", bg: WHITE, cells: [
            "Ready.",
            "Interrupted, but informed.",
            "In charge.",
            "Focused.",
            "Careful.",
            "Finished.",
            "Off the clock."
          ] },
          { label: "Risks", bg: AMBER, cells: [
            "F11 inappropriate service",
            "F39 details on a lock screen",
            "F1 over-trust of the display",
            "F6 a hidden constraint",
            "F11 advice misread",
            "F10 no audit trail",
            "F47 request stalls"
          ] },
          { label: "Design response", bg: TINT, cells: [
            "Presence shows availability, not a name, until a request is taken.",
            "The notification carries urgency and age band only.",
            "Taking it locks it. It returns if nobody acts in 10 minutes.",
            "The case view repeats what the advisor saw, with data age.",
            "No free-text decision. A short optional note with a no-names warning.",
            "Advice, role and time are logged. Overrides are reviewed with service leads.",
            "Away removes the person from the available count."
          ] }
        ]
      }
    ];
    return { journeys };
  }
}

## Artboard: Journeys4

User journeys: COO and ICB, criteria owner
## {{j.title}}
{{j.sub}}
{{s}}
{{r.label}}
{{c}}

--- script ---
class Component extends DCLogic {
  renderVals() {
    const WHITE = '#FFFFFF', TINT = '#E3F1F8', AMBER = '#FFF1DC';
    const WHITE = '#FFFFFF', TINT = '#E3F1F8', AMBER = '#FFF1DC';
    const journeys = [
      {
        title: "COO and ICB lead: alerts and the week",
        sub: "Hospital COO or ICB lead. Wants the system picture and alerts that matter, on a phone.",
        stages: ["1 Invited", "2 Set up and choose alerts", "3 Glance at home", "4 Alert arrives", "5 Acknowledge and act", "6 Weekly summary", "7 Adjust"],
        rows: [
          { label: "Does", bg: WHITE, cells: [
            "Gets a text invitation. Opens the link.",
            "Verifies the phone, adds the app to the home screen, allows notifications, chooses alerts and a PIN.",
            "Opens the app. Sees system pressure and what needs attention.",
            "Gets an escalation: a service closed, over capacity or not updated.",
            "Taps to acknowledge, phones the duty coordinator, or snoozes.",
            "Reads the week: counts, on-time updates, time to a confirmed booking.",
            "Changes alerts, quiet hours and the deputy."
          ] },
          { label: "Sees", bg: WHITE, cells: [
            "What the tool is for, in three lines.",
            "Each alert with what it means. Notifications never carry patient data.",
            "Normal, Watch or High, with counts and a short list.",
            "The service, what changed and since when.",
            "Who is alerted next if nobody acknowledges.",
            "Counts only. Groups under 10 hidden. Outcomes not shown yet.",
            "The ladder: you, your deputy, then the SPOA shift lead."
          ] },
          { label: "Feels", bg: WHITE, cells: [
            "Curious.",
            "In control.",
            "Informed.",
            "Interrupted, but it matters.",
            "Able to act.",
            "Holding evidence.",
            "Less noise."
          ] },
          { label: "Risks", bg: AMBER, cells: [
            "F41 alert fatigue",
            "F36 data leaks into telemetry",
            "F2 a stale picture",
            "F41 alerts ignored",
            "F47 nobody responds",
            "F48 unproven claims",
            "F41 too many alerts"
          ] },
          { label: "Design response", bg: TINT, cells: [
            "A short invitation with no jargon.",
            "Few alerts on by default. Quiet hours set once.",
            "One screen. No drill-down needed to know if it is bad.",
            "Escalations only for what the person chose.",
            "Acknowledging tells others it is being handled.",
            "Estimates are labelled and show their sum.",
            "Settings on one screen. A deputy is named."
          ] }
        ]
      },
      {
        title: "Criteria owner: keeping criteria current",
        sub: "Service clinical lead who owns what a service accepts. Reviews are a safety control.",
        stages: ["1 Reminder", "2 Review", "3 Confirm or change", "4 Preview", "5 Send for approval", "6 Approved or sent back", "7 Overdue"],
        rows: [
          { label: "Does", bg: WHITE, cells: [
            "Gets a reminder before the review-by date.",
            "Opens the criteria. Compares them with how the service works now.",
            "Confirms they are right, or edits needs, ages and districts.",
            "Checks what advisors will see and what changed.",
            "Adds a reason and sends for second approval.",
            "Sees the clinical lead's decision and any note.",
            "If the review is ignored, advisors see a criteria-not-reviewed flag."
          ] },
          { label: "Sees", bg: WHITE, cells: [
            "Version, review date and a two-minute task.",
            "What the service accepts and does not accept, in plain lists.",
            "Changed fields marked.",
            "The advisor card as it will look, and a before and after.",
            "That advisors still see the old version until approval.",
            "A tracker: sent, second approval, live.",
            "The consequence, and how to change the owner."
          ] },
          { label: "Feels", bg: WHITE, cells: [
            "Reminded.",
            "Careful.",
            "Responsible.",
            "Reassured.",
            "Accountable.",
            "Relieved, or clear what to fix.",
            "Prompted."
          ] },
          { label: "Risks", bg: AMBER, cells: [
            "F7 criteria out of date",
            "F7 wrong detail",
            "F11 wrong criteria go live",
            "F11 mis-set criteria",
            "F40 old version cached",
            "F47 approver absent",
            "F7 never reviewed"
          ] },
          { label: "Design response", bg: TINT, cells: [
            "The reminder uses the person's chosen channel.",
            "The last review date is visible.",
            "Confirming is a sign-off with a logged role and date.",
            "Preview before sending.",
            "Two approvals. The old version stays live until then.",
            "The cache is cleared on approval. Cases keep the version they saw.",
            "An overdue flag on the service and on advisor cards."
          ] }
        ]
      }
    ];
    return { journeys };
  }
}

## Artboard: Journeys5

User journeys: registration, multiple services
## {{j.title}}
{{j.sub}}
{{s}}
{{r.label}}
{{c}}

--- script ---
class Component extends DCLogic {
  renderVals() {
    const WHITE = '#FFFFFF', TINT = '#E3F1F8', AMBER = '#FFF1DC';
    const WHITE = '#FFFFFF', TINT = '#E3F1F8', AMBER = '#FFF1DC';
    const journeys = [
      {
        title: "Registration and approval: a new service",
        sub: "Applicant at the service, and the SPOA shift lead who checks them.",
        stages: ["1 Invited", "2 Set up", "3 Register", "4 Submitted", "5 Checks", "6 Approved, then test", "7 Live"],
        rows: [
          { label: "Does", bg: WHITE, cells: [
            "The shift lead invites a service from the scope list.",
            "The applicant verifies the phone, makes a PIN and chooses a channel.",
            "Fills five steps. The service name and ODS code are locked.",
            "Submits. Sees a tracker.",
            "The reviewer checks, calls the register number back and decides scope. A clinical lead approves the criteria.",
            "The applicant answers a test notification.",
            "The shift lead sets the service live. The reporter gets the first prompt."
          ] },
          { label: "Sees", bg: WHITE, cells: [
            "Only in-scope services can be invited.",
            "A masked number, code boxes and the home-screen guide.",
            "Errors by field, with a summary at the top.",
            "Submitted, checks, approval, test, live.",
            "Automatic checks, a call-back script and scope questions.",
            "Approve stays unavailable until the checks are done.",
            "A board preview of the new tile."
          ] },
          { label: "Feels", bg: WHITE, cells: [
            "Welcomed.",
            "Guided.",
            "Sometimes stuck.",
            "Waiting.",
            "Methodical (the reviewer).",
            "Nearly there.",
            "Part of the system."
          ] },
          { label: "Risks", bg: AMBER, cells: [
            "F26 fake service",
            "F24 SIM swap",
            "F44 hard to use",
            "F47 the queue stalls",
            "F25 skipped check",
            "F18 spoofed reporter",
            "F9 no cover"
          ] },
          { label: "Design response", bg: TINT, cells: [
            "The invitation locks the name, ODS code and mobile.",
            "Each step is one screen with a text fallback.",
            "Required and optional are written as words.",
            "A time target, and a note if changes are needed.",
            "The call-back goes to the register number, never the applicant's.",
            "A test the phone must answer.",
            "An audit record of who approved what."
          ] }
        ]
      },
      {
        title: "One phone, several services",
        sub: "A reporter who looks after more than one service on one phone.",
        stages: ["1 Added to a phone", "2 Grouped prompt", "3 Update both", "4 Change one", "5 Booking request", "6 Cover and handover", "7 Too many services"],
        rows: [
          { label: "Does", bg: WHITE, cells: [
            "The shift lead adds a service. The person accepts it.",
            "Gets one notification for two services due together.",
            "Taps Both still right, or opens each service.",
            "Changes one figure with the service name in large type.",
            "Gets a booking request for one service only.",
            "Hands one service to a cover phone for a day or a week.",
            "The lead is warned when one phone holds more than three."
          ] },
          { label: "Sees", bg: WHITE, cells: [
            "Which service, from whom, and that it will be checked.",
            "Both service names and the reply-by time.",
            "Each service is confirmed separately in the record.",
            "UCR East, not UCR West, in a dark banner.",
            "The service banner, and Confirm booking for that service.",
            "The cover number verified by a text code.",
            "A flag on the phones list."
          ] },
          { label: "Feels", bg: WHITE, cells: [
            "Asked to take on more.",
            "Efficient.",
            "In control.",
            "Careful.",
            "Clear.",
            "Supported.",
            "Stretched."
          ] },
          { label: "Risks", bg: AMBER, cells: [
            "F9 no cover",
            "F16 wrong service",
            "F20 reflex yes",
            "F22 wrong service",
            "F22 wrong service",
            "F23 phone lost",
            "F12 fatigue"
          ] },
          { label: "Design response", bg: TINT, cells: [
            "Acceptance, then the usual approval and call-back.",
            "One notification, not two.",
            "A partial reply never confirms the other service.",
            "The name is repeated in the header and the echo.",
            "Booking replies are per service.",
            "Handover moves one role, not the phone.",
            "More than three services slows replies, so it is flagged."
          ] }
        ]
      }
    ];
    return { journeys };
  }
}

## Artboard: Empathy2

Empathy maps: clinical advisor, criteria owner, approver, referrer
## Clinical advisor
Escalation point. Hypotheses to test with two or three clinical advisors.
Says
“What have they already tried?”
“I need the case, not a story.”
Thinks
“Is this really beyond the advisor’s remit?”
“If I advise wrongly, it is logged against me.”
Does
Takes one request at a time, reads the scores and the options the advisor saw, phones the advisor if unclear, chooses advice, moves on.
Feels
Interrupted but purposeful. Wary of being second-guessed.
Pains
Calls with no case ready. Repeated questions. Unclear urgency.
Gains
A structured request. What the advisor saw. Advice on one screen.
Design implications
Show what the advisor saw.
No free-text decision.
Log advice without scoring people.
## Criteria owner
Service clinical lead. Reviews are a safety control.
Says
“Is this still how we work?”
“Do not let it go out until a colleague has seen it.”
Thinks
“If the criteria are wrong, someone is hurt.”
“Will advisors read this?”
Does
Gets a reminder, reviews, confirms or edits, previews, sends for second approval.
Feels
Responsible and short of time. Reassured by a second approval.
Pains
Reminders that come too late. Dense edit forms. No sense of what advisors see.
Gains
A two-minute confirm. A preview. A version history.
Design implications
Confirm-or-update pattern.
Preview before sending.
Show the consequence of an overdue review.
## Approver
Shift lead reviewing a registration.
Says
“Is this really the service we invited?”
“I will phone the register number, not theirs.”
Thinks
“A fake service could divert patients.”
“Is it in scope?”
Does
Opens the queue, reads the automatic checks, calls back, decides scope, approves or sends back, runs the go-live test.
Feels
Careful. A little burdened by the queue. Confident when the script is clear.
Pains
Unclear scope. Missing numbers. Interruptions mid-check.
Gains
A scripted call-back. Locked fields. An audit record.
Design implications
Approve stays unavailable until the checks are done.
A call-back script.
A deputy and time targets.
## Referrer
Ambulance crew or care home. Now reached through booking by text.
Says
“I need a yes or no, and a name.”
“I am on scene. I cannot hold.”
Thinks
“If they refuse, what do I do?”
“Will they call me back?”
Does
Phones the SPOA, gives age, needs and scores, waits, hears the outcome and the service.
Feels
Time-pressured and defensive about the decision. Relieved by a quick, clear answer.
Pains
Repeated questions. A refusal with no alternative. A service that withdraws after confirming.
Gains
A named service and a time. A call back if it changes. No re-explaining.
Design implications
Never end the call on a refusal.
A withdrawal prompts a call back.
The advisor script uses what the tool shows.

## Artboard: Main

Call-centre wall board
## Dorset urgent care capacity
 Single point of access
 Sample data
14:12
Friday 23 October
{{t.name}}
{{t.type}}
 {{t.status}}
{{t.big}}
{{t.unit}}
{{t.meta}}
{{t.barLabel}}
{{t.age}}
Accepting
Limited: phone to confirm
Not accepting
Over capacity
Not updated: treat as unknown, phone
No patient information on this screen

--- script ---
class Component extends DCLogic {
  renderVals() {
    const S = {
      open:    { status: 'Accepting', bg: '#FFFFFF', border: '3px solid #0B5C8C', chipBg: '#0B5C8C', chipFg: '#FFFFFF', chipBorder: '2px solid #0B5C8C', numColor: '#0B3F61', bar: '#0B5C8C', ageColor: '#44555D', ageWeight: '400' },
      limited: { status: 'Limited', bg: '#FFFFFF', border: '3px solid #A34700', chipBg: '#A34700', chipFg: '#FFFFFF', chipBorder: '2px solid #A34700', numColor: '#7A3500', bar: '#A34700', ageColor: '#44555D', ageWeight: '400' },
      closed:  { status: 'Not accepting', bg: '#E9EDEF', border: '3px solid #3A4750', chipBg: '#3A4750', chipFg: '#FFFFFF', chipBorder: '2px solid #3A4750', numColor: '#3A4750', bar: '#3A4750', ageColor: '#44555D', ageWeight: '400' },
      surge:   { status: 'Over capacity', bg: '#FFFFFF', border: '3px solid #6B2C91', chipBg: '#6B2C91', chipFg: '#FFFFFF', chipBorder: '2px solid #6B2C91', numColor: '#4B1C69', bar: 'repeating-linear-gradient(135deg,#6B2C91 0 8px,#9A6BB8 8px 16px)', ageColor: '#44555D', ageWeight: '400' },
      unknown: { status: 'Not updated', bg: 'repeating-linear-gradient(135deg,#F1F3F4 0 12px,#E4E8EA 12px 24px)', border: '3px dashed #6B7B83', chipBg: '#FFFFFF', chipFg: '#26343B', chipBorder: '2px dashed #6B7B83', numColor: '#6B7B83', bar: 'repeating-linear-gradient(135deg,#9AA7AD 0 6px,#DDE3E6 6px 12px)', ageColor: '#26343B', ageWeight: '700' }
    };
    const raw = [
      { k: 'open', name: 'UCR West', type: 'Urgent community response', big: '4', unit: 'referrals in the next 2 hrs', meta: 'Response time about 1 hr 20', pct: 50, bar: 'Used 4 of 8', age: 'Updated 9 min ago · next due 14:30' },
      { k: 'limited', name: 'UCR East', type: 'Urgent community response', big: '1', unit: 'referral in the next 2 hrs', meta: 'Response time about 2 hrs', pct: 88, bar: 'Used 7 of 8', age: 'Updated 31 min ago · next due 14:30' },
      { k: 'open', name: 'SDEC · Site 1', type: 'Same day emergency care', big: '6', unit: 'slots left today', meta: 'Referral cut-off 17:00', pct: 40, bar: 'Used 4 of 10', age: 'Updated 1 hr 5 min ago · next due 16:00' },
      { k: 'closed', name: 'SDEC · Site 2', type: 'Same day emergency care', big: '0', unit: 'slots left today', meta: 'Closed to referrals since 13:30', pct: 100, bar: 'Used 8 of 8', age: 'Updated 38 min ago · next due 16:00' },
      { k: 'limited', name: 'Community hospital · Ward A', type: 'Inpatient beds', big: '2', unit: 'beds free', meta: 'Both women only · no side room', pct: 83, bar: 'Used 10 of 12', age: 'Updated 2 hrs 10 min ago · next due 17:00' },
      { k: 'open', name: 'Community hospital · Ward B', type: 'Inpatient beds', big: '5', unit: 'beds free', meta: 'Rehab · 1 side room', pct: 58, bar: 'Used 7 of 12', age: 'Updated 2 hrs 10 min ago · next due 17:00' },
      { k: 'surge', name: 'Hospital at home', type: 'Virtual beds', big: '+2', unit: 'over established capacity', meta: 'Escalation in place', pct: 100, bar: 'Used 14 of 12', age: 'Updated 14 min ago · next due 16:00' },
      { k: 'unknown', name: 'Virtual ward · frailty', type: 'Virtual beds', big: '?', unit: 'Phone to confirm', meta: 'Last reported 3 beds free', pct: 100, bar: 'Used ? of 10', age: 'Not updated for 4 hrs 10 min · was due 12:00' },
      { k: 'open', name: 'Reablement', type: 'Care packages', big: '3', unit: 'packages today', meta: 'Postcode catchment applies', pct: 70, bar: 'Used 7 of 10', age: 'Updated 3 hrs ago · next due 09:00 tomorrow' }
    ];
    const tiles = raw.map((r) => {
      const s = S[r.k];
      return {
        name: r.name, type: r.type, big: r.big, unit: r.unit, meta: r.meta, usedPct: r.pct, barLabel: r.bar, age: r.age,
        status: s.status, bg: s.bg, border: s.border, chipBg: s.chipBg, chipFg: s.chipFg, chipBorder: s.chipBorder,
        numColor: s.numColor, barFill: s.bar, ageColor: s.ageColor, ageWeight: s.ageWeight,
        isOpen: r.k === 'open', isLimited: r.k === 'limited', isClosed: r.k === 'closed', isSurge: r.k === 'surge', isUnknown: r.k === 'unknown'
      };
    });
    return { tiles };
  }
}

## Artboard: TileStates

Wall tile: pending booking states
1 Request sent
Available stays at 4. Pending shows apart.
UCR West
Urgent community response
Accepting
4
referrals in the next 2 hrs
1 pending
Used 4 of 8 · 1 pending
Updated 9 min ago · next due 14:30
2 Confirmed by text
Available drops to 3. Pending clears.
UCR West
Urgent community response
Accepting
3
referrals in the next 2 hrs
Response time about 1 hr 20
Used 5 of 8
Booked 14:19 · next update due 14:30
3 Declined, or no reply at 10 min
Pending clears. Available returns to 4.
UCR West
Urgent community response
Accepting
4
referrals in the next 2 hrs
Response time about 1 hr 20
Used 4 of 8
Updated 9 min ago · next due 14:30

## Artboard: BoardDown

Wall board: tool offline
## Dorset urgent care capacity
 Single point of access
 Sample data
Tool offline since 14:02
Figures are the last known and may be wrong. Use the whiteboard and phone process.
14:12
Friday 23 October
{{t.name}}
{{t.type}}
 {{t.status}}
{{t.big}}
{{t.unit}}
{{t.meta}}
{{t.barLabel}}
{{t.age}}
Accepting
Limited: phone to confirm
Not accepting
Over capacity
Not updated: treat as unknown, phone
No patient information on this screen

--- script ---
class Component extends DCLogic {
  renderVals() {
    const S = {
      open:    { status: 'Accepting', bg: '#FFFFFF', border: '3px solid #0B5C8C', chipBg: '#0B5C8C', chipFg: '#FFFFFF', chipBorder: '2px solid #0B5C8C', numColor: '#0B3F61', bar: '#0B5C8C', ageColor: '#44555D', ageWeight: '400' },
      limited: { status: 'Limited', bg: '#FFFFFF', border: '3px solid #A34700', chipBg: '#A34700', chipFg: '#FFFFFF', chipBorder: '2px solid #A34700', numColor: '#7A3500', bar: '#A34700', ageColor: '#44555D', ageWeight: '400' },
      closed:  { status: 'Not accepting', bg: '#E9EDEF', border: '3px solid #3A4750', chipBg: '#3A4750', chipFg: '#FFFFFF', chipBorder: '2px solid #3A4750', numColor: '#3A4750', bar: '#3A4750', ageColor: '#44555D', ageWeight: '400' },
      surge:   { status: 'Over capacity', bg: '#FFFFFF', border: '3px solid #6B2C91', chipBg: '#6B2C91', chipFg: '#FFFFFF', chipBorder: '2px solid #6B2C91', numColor: '#4B1C69', bar: 'repeating-linear-gradient(135deg,#6B2C91 0 8px,#9A6BB8 8px 16px)', ageColor: '#44555D', ageWeight: '400' },
      unknown: { status: 'Last known', bg: 'repeating-linear-gradient(135deg,#F1F3F4 0 12px,#E4E8EA 12px 24px)', border: '3px dashed #6B7B83', chipBg: '#FFFFFF', chipFg: '#26343B', chipBorder: '2px dashed #6B7B83', numColor: '#6B7B83', bar: 'repeating-linear-gradient(135deg,#9AA7AD 0 6px,#DDE3E6 6px 12px)', ageColor: '#26343B', ageWeight: '700' }
    };
    const raw = [
      { k: 'unknown', name: 'UCR West', type: 'Urgent community response', big: '4', unit: 'referrals in the next 2 hrs', meta: 'Last known 13:58', pct: 50, bar: 'Used 4 of 8', age: 'Do not rely on this. Phone to confirm.' },
      { k: 'unknown', name: 'UCR East', type: 'Urgent community response', big: '1', unit: 'referral in the next 2 hrs', meta: 'Last known 13:40', pct: 88, bar: 'Used 7 of 8', age: 'Do not rely on this. Phone to confirm.' },
      { k: 'unknown', name: 'SDEC · Site 1', type: 'Same day emergency care', big: '6', unit: 'slots left today', meta: 'Last known 13:05', pct: 40, bar: 'Used 4 of 10', age: 'Do not rely on this. Phone to confirm.' },
      { k: 'unknown', name: 'SDEC · Site 2', type: 'Same day emergency care', big: '0', unit: 'slots left today', meta: 'Last known 13:30', pct: 100, bar: 'Used 8 of 8', age: 'Do not rely on this. Phone to confirm.' },
      { k: 'unknown', name: 'Community hospital · Ward A', type: 'Inpatient beds', big: '2', unit: 'beds free', meta: 'Last known 12:00', pct: 83, bar: 'Used 10 of 12', age: 'Do not rely on this. Phone to confirm.' },
      { k: 'unknown', name: 'Community hospital · Ward B', type: 'Inpatient beds', big: '5', unit: 'beds free', meta: 'Last known 12:00', pct: 58, bar: 'Used 7 of 12', age: 'Do not rely on this. Phone to confirm.' },
      { k: 'unknown', name: 'Hospital at home', type: 'Virtual beds', big: '+2', unit: 'over established capacity', meta: 'Last known 13:58', pct: 100, bar: 'Used 14 of 12', age: 'Do not rely on this. Phone to confirm.' },
      { k: 'unknown', name: 'Virtual ward · frailty', type: 'Virtual beds', big: '3', unit: 'beds free', meta: 'Last known 10:00', pct: 70, bar: 'Used 7 of 10', age: 'Do not rely on this. Phone to confirm.' },
      { k: 'unknown', name: 'Reablement', type: 'Care packages', big: '3', unit: 'packages today', meta: 'Last known 09:00', pct: 70, bar: 'Used 7 of 10', age: 'Do not rely on this. Phone to confirm.' }
    ];
    const tiles = raw.map((r) => {
      const s = S[r.k];
      return {
        name: r.name, type: r.type, big: r.big, unit: r.unit, meta: r.meta, usedPct: r.pct, barLabel: r.bar, age: r.age,
        status: s.status, bg: s.bg, border: s.border, chipBg: s.chipBg, chipFg: s.chipFg, chipBorder: s.chipBorder,
        numColor: s.numColor, barFill: s.bar, ageColor: s.ageColor, ageWeight: s.ageWeight,
        isOpen: r.k === 'open', isLimited: r.k === 'limited', isClosed: r.k === 'closed', isSurge: r.k === 'surge', isUnknown: r.k === 'unknown'
      };
    });
    return { tiles };
  }
}

## Artboard: BoardSurge

Wall board: system surge
## Dorset urgent care capacity
 Single point of access
 Sample data
System under pressure
All 9 services are limited, not accepting or over capacity.
14:12
Friday 23 October
{{t.name}}
{{t.type}}
 {{t.status}}
{{t.big}}
{{t.unit}}
{{t.meta}}
{{t.barLabel}}
{{t.age}}
Accepting
Limited: phone to confirm
Not accepting
Over capacity
Not updated: treat as unknown, phone
No patient information on this screen

--- script ---
class Component extends DCLogic {
  renderVals() {
    const S = {
      open:    { status: 'Accepting', bg: '#FFFFFF', border: '3px solid #0B5C8C', chipBg: '#0B5C8C', chipFg: '#FFFFFF', chipBorder: '2px solid #0B5C8C', numColor: '#0B3F61', bar: '#0B5C8C', ageColor: '#44555D', ageWeight: '400' },
      limited: { status: 'Limited', bg: '#FFFFFF', border: '3px solid #A34700', chipBg: '#A34700', chipFg: '#FFFFFF', chipBorder: '2px solid #A34700', numColor: '#7A3500', bar: '#A34700', ageColor: '#44555D', ageWeight: '400' },
      closed:  { status: 'Not accepting', bg: '#E9EDEF', border: '3px solid #3A4750', chipBg: '#3A4750', chipFg: '#FFFFFF', chipBorder: '2px solid #3A4750', numColor: '#3A4750', bar: '#3A4750', ageColor: '#44555D', ageWeight: '400' },
      surge:   { status: 'Over capacity', bg: '#FFFFFF', border: '3px solid #6B2C91', chipBg: '#6B2C91', chipFg: '#FFFFFF', chipBorder: '2px solid #6B2C91', numColor: '#4B1C69', bar: 'repeating-linear-gradient(135deg,#6B2C91 0 8px,#9A6BB8 8px 16px)', ageColor: '#44555D', ageWeight: '400' },
      unknown: { status: 'Not updated', bg: 'repeating-linear-gradient(135deg,#F1F3F4 0 12px,#E4E8EA 12px 24px)', border: '3px dashed #6B7B83', chipBg: '#FFFFFF', chipFg: '#26343B', chipBorder: '2px dashed #6B7B83', numColor: '#6B7B83', bar: 'repeating-linear-gradient(135deg,#9AA7AD 0 6px,#DDE3E6 6px 12px)', ageColor: '#26343B', ageWeight: '700' }
    };
    const raw = [
      {"k": "limited", "name": "UCR West", "type": "Urgent community response", "big": "1", "unit": "referral in the next 2 hrs", "meta": "Response time about 2 hrs 30", "pct": 88, "bar": "Used 7 of 8 \u00b7 1 pending", "age": "Updated 6 min ago \u00b7 next due 14:30"},
      {"k": "closed", "name": "UCR East", "type": "Urgent community response", "big": "0", "unit": "referrals in the next 2 hrs", "meta": "Not accepting since 13:10", "pct": 100, "bar": "Used 8 of 8", "age": "Updated 22 min ago \u00b7 next due 14:30"},
      {"k": "limited", "name": "SDEC \u00b7 Site 1", "type": "Same day emergency care", "big": "1", "unit": "slot left today", "meta": "Referral cut-off 17:00", "pct": 90, "bar": "Used 9 of 10", "age": "Updated 18 min ago \u00b7 next due 15:00"},
      {"k": "closed", "name": "SDEC \u00b7 Site 2", "type": "Same day emergency care", "big": "0", "unit": "slots left today", "meta": "Not accepting since 12:50", "pct": 100, "bar": "Used 8 of 8", "age": "Updated 25 min ago \u00b7 next due 15:00"},
      {"k": "closed", "name": "Community hospital \u00b7 Ward A", "type": "Inpatient beds", "big": "0", "unit": "beds free", "meta": "Full", "pct": 100, "bar": "Used 12 of 12", "age": "Updated 1 hr 10 min ago \u00b7 next due 17:00"},
      {"k": "limited", "name": "Community hospital \u00b7 Ward B", "type": "Inpatient beds", "big": "1", "unit": "bed free", "meta": "Male \u00b7 no side room", "pct": 92, "bar": "Used 11 of 12", "age": "Updated 1 hr 10 min ago \u00b7 next due 17:00"},
      {"k": "surge", "name": "Hospital at home", "type": "Virtual beds", "big": "+4", "unit": "over established capacity", "meta": "Escalation in place", "pct": 100, "bar": "Used 16 of 12 \u00b7 1 pending", "age": "Updated 11 min ago \u00b7 next due 15:00"},
      {"k": "surge", "name": "Virtual ward \u00b7 frailty", "type": "Virtual beds", "big": "+1", "unit": "over established capacity", "meta": "Escalation in place", "pct": 100, "bar": "Used 11 of 10", "age": "Updated 40 min ago \u00b7 next due 15:00"},
      {"k": "limited", "name": "Reablement", "type": "Care packages", "big": "1", "unit": "package today", "meta": "Postcode catchment applies", "pct": 90, "bar": "Used 9 of 10", "age": "Updated 2 hrs ago \u00b7 next due 09:00 tomorrow"}
    ];
    const tiles = raw.map((r) => {
      const s = S[r.k];
      return {
        name: r.name, type: r.type, big: r.big, unit: r.unit, meta: r.meta, usedPct: r.pct, barLabel: r.bar, age: r.age,
        status: r.st || s.status, bg: s.bg, border: s.border, chipBg: s.chipBg, chipFg: s.chipFg, chipBorder: s.chipBorder,
        numColor: s.numColor, barFill: s.bar, ageColor: s.ageColor, ageWeight: s.ageWeight,
        isOpen: r.k === 'open', isLimited: r.k === 'limited', isClosed: r.k === 'closed', isSurge: r.k === 'surge', isUnknown: r.k === 'unknown'
      };
    });
    return { tiles };
  }
}

## Artboard: BoardQuiet

Wall board: overnight
## Dorset urgent care capacity
 Single point of access
 Sample data
02:40
Saturday 24 October
{{t.name}}
{{t.type}}
 {{t.status}}
{{t.big}}
{{t.unit}}
{{t.meta}}
{{t.barLabel}}
{{t.age}}
Accepting
Limited: phone to confirm
Not accepting
Over capacity
Not updated: treat as unknown, phone
No patient information on this screen

--- script ---
class Component extends DCLogic {
  renderVals() {
    const S = {
      open:    { status: 'Accepting', bg: '#FFFFFF', border: '3px solid #0B5C8C', chipBg: '#0B5C8C', chipFg: '#FFFFFF', chipBorder: '2px solid #0B5C8C', numColor: '#0B3F61', bar: '#0B5C8C', ageColor: '#44555D', ageWeight: '400' },
      limited: { status: 'Limited', bg: '#FFFFFF', border: '3px solid #A34700', chipBg: '#A34700', chipFg: '#FFFFFF', chipBorder: '2px solid #A34700', numColor: '#7A3500', bar: '#A34700', ageColor: '#44555D', ageWeight: '400' },
      closed:  { status: 'Not accepting', bg: '#E9EDEF', border: '3px solid #3A4750', chipBg: '#3A4750', chipFg: '#FFFFFF', chipBorder: '2px solid #3A4750', numColor: '#3A4750', bar: '#3A4750', ageColor: '#44555D', ageWeight: '400' },
      surge:   { status: 'Over capacity', bg: '#FFFFFF', border: '3px solid #6B2C91', chipBg: '#6B2C91', chipFg: '#FFFFFF', chipBorder: '2px solid #6B2C91', numColor: '#4B1C69', bar: 'repeating-linear-gradient(135deg,#6B2C91 0 8px,#9A6BB8 8px 16px)', ageColor: '#44555D', ageWeight: '400' },
      unknown: { status: 'Not updated', bg: 'repeating-linear-gradient(135deg,#F1F3F4 0 12px,#E4E8EA 12px 24px)', border: '3px dashed #6B7B83', chipBg: '#FFFFFF', chipFg: '#26343B', chipBorder: '2px dashed #6B7B83', numColor: '#6B7B83', bar: 'repeating-linear-gradient(135deg,#9AA7AD 0 6px,#DDE3E6 6px 12px)', ageColor: '#26343B', ageWeight: '700' }
    };
    const raw = [
      {"k": "closed", "name": "UCR West", "type": "Urgent community response", "big": "0", "unit": "referrals in the next 2 hrs", "meta": "Reopens 08:00", "pct": 100, "bar": "Out of hours", "age": "Closed overnight", "st": "Out of hours"},
      {"k": "closed", "name": "UCR East", "type": "Urgent community response", "big": "0", "unit": "referrals in the next 2 hrs", "meta": "Reopens 08:00", "pct": 100, "bar": "Out of hours", "age": "Closed overnight", "st": "Out of hours"},
      {"k": "closed", "name": "SDEC \u00b7 Site 1", "type": "Same day emergency care", "big": "0", "unit": "slots left today", "meta": "Reopens 08:00", "pct": 100, "bar": "Out of hours", "age": "Closed overnight", "st": "Out of hours"},
      {"k": "closed", "name": "SDEC \u00b7 Site 2", "type": "Same day emergency care", "big": "0", "unit": "slots left today", "meta": "Reopens 08:00", "pct": 100, "bar": "Out of hours", "age": "Closed overnight", "st": "Out of hours"},
      {"k": "open", "name": "Community hospital \u00b7 Ward A", "type": "Inpatient beds", "big": "3", "unit": "beds free", "meta": "Women only \u00b7 1 side room", "pct": 75, "bar": "Used 9 of 12", "age": "Updated 1 hr 20 min ago \u00b7 next due 06:00"},
      {"k": "limited", "name": "Community hospital \u00b7 Ward B", "type": "Inpatient beds", "big": "1", "unit": "bed free", "meta": "Male \u00b7 no side room", "pct": 92, "bar": "Used 11 of 12", "age": "Updated 1 hr 20 min ago \u00b7 next due 06:00"},
      {"k": "open", "name": "Hospital at home", "type": "Virtual beds", "big": "2", "unit": "virtual beds free", "meta": "Admissions until 06:00", "pct": 80, "bar": "Used 8 of 10", "age": "Updated 42 min ago \u00b7 next due 06:00"},
      {"k": "closed", "name": "Virtual ward \u00b7 frailty", "type": "Virtual beds", "big": "0", "unit": "virtual beds free", "meta": "Reopens 08:00", "pct": 100, "bar": "Out of hours", "age": "Closed overnight", "st": "Out of hours"},
      {"k": "closed", "name": "Reablement", "type": "Care packages", "big": "0", "unit": "packages today", "meta": "Reopens 08:00", "pct": 100, "bar": "Out of hours", "age": "Closed overnight", "st": "Out of hours"}
    ];
    const tiles = raw.map((r) => {
      const s = S[r.k];
      return {
        name: r.name, type: r.type, big: r.big, unit: r.unit, meta: r.meta, usedPct: r.pct, barLabel: r.bar, age: r.age,
        status: r.st || s.status, bg: s.bg, border: s.border, chipBg: s.chipBg, chipFg: s.chipFg, chipBorder: s.chipBorder,
        numColor: s.numColor, barFill: s.bar, ageColor: s.ageColor, ageWeight: s.ageWeight,
        isOpen: r.k === 'open', isLimited: r.k === 'limited', isClosed: r.k === 'closed', isSurge: r.k === 'surge', isUnknown: r.k === 'unknown'
      };
    });
    return { tiles };
  }
}

## Artboard: Reporter

Capacity request by text
1 Request: text
[btn] [Back] 
D
DIUCS capacity
07700 900123
Today 10:00
DIUCS: UCR West. We have 3 referrals in the next 2 hrs (as of 08:15). Confirm or update: diucs.example/k3F9a Or reply Y, or a new number. By 10:30.
Message[input text value='' placeholder='Text message']
[btn] [Send] 
2 Response: link page
diucs.example/k3F9a
DIUCS capacity update
## UCR West
We have 3 referrals in the next 2 hours, as of 08:15. Still right?
[btn] Yes, still 3
Or send a new number
[btn] [Decrease by one] 
Referrals in the next 2 hours[input text value='4' placeholder='']
[btn] [Increase by one] 
referrals · usual range 0 to 8
[btn] Send new number
[btn] We are closed to referrals
No login. This link is for this phone, works once, and expires at 10:30. Next update due 12:00.
3 Confirmation
diucs.example/k3F9a
## Thank you
UCR West: 4 referrals in the next 2 hrs, recorded at 10:12.
Next update due 12:00
[btn] Something wrong? Change itSee the live board
You can close this page.

## Artboard: Reporter2

Reporter: edge cases
Text: late reply, correction, Y limit
[btn] [Back] 
D
DIUCS capacity
07700 900123
Today 12:00
DIUCS: UCR West. We have 3 referrals in the next 2 hrs (as of 08:15). Reply Y if right, or send the new number (0 = closed). By 12:30.
5
12:41
Too late: the 12:30 cut-off had passed, so 5 was not used. New question: UCR West has 3 referrals recorded. Reply Y if right, or send the new number, by 13:11.
Correcting a reply
4
14:10
Thanks. UCR West: updated to 4 referrals, as of 14:10.
3
14:14
Updated: UCR West 3 referrals, as of 14:14. Replaces 4.
Third Y in a row
Y
16:01
Y was used twice already. Please send the number for UCR West.
Message[input text value='' placeholder='Text message']
[btn] [Send] 
Email link: after Send
## Thank you
UCR West: 3 referrals in the next 2 hrs, recorded at 14:12.
Next update due 16:00
[btn] Something wrong? Change itSee the live board
You can close this page. 
Email link: expired or already used
## This link has expired
It closed at 12:30, so nothing was recorded from it.
[btn] Send me a new link
Or reply to the text message instead.
A link works once. If you already sent your update, you will find it on the board.

## Artboard: ReporterFirst

Reporter: first report
Text: no figure recorded yet
[btn] [Back] 
D
DIUCS capacity
07700 900123
Today 08:00
DIUCS: UCR West. How many referrals can you take in the next 2 hrs? Send a number (0 = closed). By 08:30.
4
08:06
Thanks. UCR West: 4 referrals, as of 08:06. Next prompt 10:00.
Message[input text value='' placeholder='Text message']
[btn] [Send] 
Email link: no figure recorded yet
DIUCS capacity update
## UCR West
How many referrals can you take in the next 2 hours?
[btn] [Decrease by one] 
Referrals in the next 2 hours[input text value='' placeholder='–']
[btn] [Increase by one] 
referrals · usual range 0 to 8
[btn] Choose a number to send
[btn] We are closed to referrals
This link works once and expires at 08:30. Next update due 10:00.

## Artboard: EmailCapacity

Capacity request by email
1 Request: email
Mail · Inbox
Mail
Inbox 1
Sent items
Drafts
Archive
Inbox
DIUCS Capacity10:00
UCR West: confirm or update by 10:30
We have 3 referrals in the next 2 hours, as of 08:15
Ward manager09:12
Rota change next week
Please see the attached rota
EstatesMon
Lift maintenance Thursday
Works start at 08:00
UCR West: confirm or update by 10:30
D
DIUCS Capacity <capacity@diucs.example>
To: UCR West duty coordinator · 10:00
We have 3 referrals in the next 2 hours, as of 08:15.
Please confirm this is right, or update it, by 10:30.Confirm or update
The link works once, needs no login, and expires at 10:30. This email has no patient information. Replies to this address are not read.
2 Response: link page
diucs.example/k3F9a
DIUCS capacity update
## UCR West
We have 3 referrals in the next 2 hours, as of 08:15. Still right?
[btn] Yes, still 3
Or send a new number
[btn] [Decrease by one] 
Referrals in the next 2 hours[input text value='4' placeholder='']
[btn] [Increase by one] 
referrals · usual range 0 to 8
[btn] Send new number
[btn] We are closed to referrals
No login. This link works once and expires at 10:30. Next update due 12:00.
3 Confirmation
diucs.example/k3F9a
## Thank you
UCR West: 4 referrals in the next 2 hrs, recorded at 10:12.
Next update due 12:00
[btn] Something wrong? Change itSee the live board
You can close this page.

## Artboard: Booking

Booking request: service reply and advisor states
Service phone: booking request
[btn] [Back] 
D
DIUCS capacity
07700 900123
Today 14:16
DIUCS REQUEST 4821: UCR West. Age 80+, fall and frailty, response within 2 hrs. Referral details follow in SystmOne. Reply CONFIRMED or DECLINE by 14:26.
CONFIRMED
14:19
Booked: 4821, UCR West, confirmed 14:19. Thank you.
If declined
Noted: 4821 declined. Optional reason: reply 1 full, 2 outside criteria, 3 other.
Message
 [input text value='' placeholder='Text message']
[btn] [Send] 
Advisor view: what happens to the card
UCR West
 Requested
Not booked yet
Text sent 14:16 · delivered. Waiting for CONFIRMED. Phone prompt at 14:21. Request expires 14:26.
Colleagues see 1 pending on the board.
[btn] Phone them instead
[btn] Cancel request
UCR West
 Booked
Confirmed 14:19
Reference 4821. Capacity reduced by 1. Next: complete the referral in SystmOne.
[btn] Copy summary for SystmOne
[btn] Record outcome
UCR West
 Declined
Not booked
Declined 14:19. Reason: outside criteria. Pending count released. Choose another option or phone to discuss.
[btn] Back to options
[btn] Phone to discuss
UCR West
 No reply
Not booked. Phone now.
No reply after 5 min, so you were prompted to phone. The request expired at 10 min and the pending count is released. Do not assume it was accepted.
[btn] Phone UCR West
[btn] Try next option

## Artboard: BookingSms

Booking request by text
1 Request: text
[btn] [Back] 
D
DIUCS capacity
07700 900123
Today 14:16
DIUCS REQUEST 4821: UCR West. Age 80+, fall and frailty, within 2 hrs. Referral details follow in SystmOne. Reply CONFIRMED or DECLINE, or open diucs.example/b4821 by 14:26.
Message[input text value='' placeholder='Text message']
[btn] [Send] 
2 Response: reply
[btn] [Back] 
D
DIUCS capacity
07700 900123
Today 14:16
DIUCS REQUEST 4821: UCR West. Age 80+, fall and frailty, within 2 hrs. Referral details follow in SystmOne. Reply CONFIRMED or DECLINE, or open diucs.example/b4821 by 14:26.
Message[input text value='CONFIRMED' placeholder='Text message']
[btn] [Send] 
3 Confirmation
[btn] [Back] 
D
DIUCS capacity
07700 900123
Today 14:16
DIUCS REQUEST 4821: UCR West. Age 80+, fall and frailty, within 2 hrs. Referral details follow in SystmOne. Reply CONFIRMED or DECLINE, or open diucs.example/b4821 by 14:26.
CONFIRMED
14:19
Booked: 4821, UCR West, confirmed 14:19. Thank you.
Message[input text value='' placeholder='Text message']
[btn] [Send]

## Artboard: BookingEmail

Booking request by email
1 Request: email
Mail · Inbox
Mail
Inbox 1
Sent items
Drafts
Archive
Inbox
DIUCS Capacity10:00
Booking request 4821: UCR West, reply by 14:26
Age band 80+, fall and frailty, within 2 hrs
Ward manager09:12
Rota change next week
Please see the attached rota
EstatesMon
Lift maintenance Thursday
Works start at 08:00
Booking request 4821: UCR West, reply by 14:26
D
DIUCS Capacity <capacity@diucs.example>
To: UCR West duty coordinator · 10:00
Booking request 4821 for UCR West.
Age band 80+
Need: fall and frailty
Response wanted: within 2 hrs
Referral details follow in SystmOne.
Please review and reply by 14:26.Review request
Opening the link does not book anything. You confirm on the next page. The link works once and needs no login.
2 Response: decision page
diucs.example/b4821
DIUCS booking request · Reference 4821
## UCR West
Age band 80+
Need Fall and frailty
Response wanted Within 2 hrs
Referral details follow in SystmOne.
[btn] Confirm booking
Or decline. Why? (optional)
[btn] We are full
[btn] Outside our criteria
[btn] Staffing or transport
[btn] Other
[btn] Decline
Not booked until you confirm. Reply by 14:26.
3 Confirmation
diucs.example/b4821
## Booked
Reference 4821, UCR West. Confirmed 14:19. The advisor has been told.
Referral details follow in SystmOne.
Something changed? Phone the SPOA on [SPOA phone number].
You can close this page.

## Artboard: BookingExceptions

Booking exceptions: withdraw, not reached, cancel
1 Service: booked
[btn] [Back] 
Booking 4821
Booked
## UCR West
Confirmed 14:19. Referral details follow in SystmOne.
Age band 80+
Need Fall and frailty
Wanted Within 2 hrs
Something changed? Tell us here so the SPOA can act at once.
[btn] We cannot take this patient now
[btn] Patient not found or not there
[btn] Close
2 Service: withdraw
[btn] [Back] 
Withdraw
## Why can you no longer take this patient?
[btn] We are now full
[btn] Staffing
[btn] We cannot reach the patient
[btn] Other
The SPOA is told at once and will find another service. The patient will not be left without a plan.
[btn] Withdraw booking
[btn] Back
3 Service: withdrawn
[btn] [Back] 
Withdrawn
## Withdrawn
The SPOA has been told and is finding another service.
If the patient has already been told you are coming, phone the SPOA on [SPOA phone number] now.
[btn] Close
4 Service: not reached
[btn] [Back] 
Not reached
## Patient not found or not there
[btn] Not at the address
[btn] No answer at the door
[btn] Gone to hospital
[btn] Other
The SPOA is told and will phone the caller.
[btn] Save
[btn] Back
5 Advisor: withdrawal alert
[btn] [Back] 
UCR West withdrew
Withdrawn
## UCR West can no longer take this patient
Reason: staffing. Withdrawn 14:41.
Phone the caller now.
Tell them another service is being found.
If nobody acts within 10 minutes the shift lead is alerted.
[btn] See options again
[btn] Ask a clinical advisor
[btn] Phone the caller
6 Advisor: cancel booking
[btn] [Back] 
Cancel booking
## Cancel the booking with UCR West?
[btn] Caller declined
[btn] No longer needed
[btn] Other route found
[btn] Entered in error
The service is told by its own channel. The slot goes back to available.
[btn] Cancel booking
[btn] Keep booking
7 Service: cancelled
[btn] [Back] 
Booking 4821
Cancelled
## Cancelled by the SPOA
Booking 4821 was cancelled at 14:40. No action needed.
[btn] Close

## Artboard: AdvisorStart

Advisor: sign in and home
DIUCS capacity
## Sign in
DIUCS capacity
Use your Trust staff account. There is no new password.
[btn] Sign in with your Trust account
Having trouble? Ask your shift lead to check your access.
## Ready for calls
Advisor home
[btn] Start a new call
Board right now
4
2
1
1
1
[btn] Open the wall board view
No open cases. Nothing from earlier calls is shown here.

## Artboard: Advisor

Advisor: live call
DIUCS capacity
 Call in progress · 02:14 · Ambulance crew
 Advisor
 A
Needs
2
Options
3
Request
4
Outcome
Now: compare the options and check the criteria. Next: request a booking.
## Patient needs
Age
[btn] 0 to 15
[btn] 16 to 64
[btn] 65 to 79
[btn] 80+
Where is the patient? Postcode
 [input text value='DT4 8XX' placeholder='']
What do they need?
[btn] Fall, no injury
[btn] Frailty
[btn] IV therapy
[btn] Wound care
[btn] Palliative
[btn] More needs
How soon?
[btn] Within 2 hrs
[btn] Today
[btn] Planned
Score from the referrer (optional)
[btn] NHS Pathways Dx
[btn] Ambulance category
[btn] Manchester triage
[btn] NEWS2
[btn] Frailty scale
[btn] Not given
NEWS2 (0 to 20)
 [input text value='2' placeholder='']
Clinical Frailty Scale (1 to 9)
 [input text value='6' placeholder='']
Recorded as the referrer gave it. Fixed choices, no free text. The tool does not calculate or check scores.
## 3 services meet this patient's criteria
Sorted by travel time. Not ranked.
{{c.name}}
{{c.type}}
 {{c.status}}
{{c.big}}
{{c.unit}}
Response or travel: {{c.travel}}
Data age: {{c.age}}
Why it fits
 {{f}}
Check before offering
 {{w}}
[btn] Request booking
[btn] Criteria
[btn] I phoned
 3 services not suitable, and why
SDEC · Site 2: not accepting since 13:30
Virtual ward · frailty: not updated for 4 hrs 10 min. Phone to confirm.
Reablement: not for a same-day need
No patient name is stored. Postcode and needs are cleared after the call record closes.
[btn] Ask clinical advisor
[btn] Record outcome
[btn] Copy summary for SystmOne

--- script ---
class Component extends DCLogic {
  renderVals() {
    const cards = [
      { name: 'UCR West', type: 'Urgent community response', status: 'Accepting', kind: 'open', big: '4', unit: 'referrals in the next 2 hrs', travel: 'Visits the patient, about 1 hr 20', age: '9 min ago',
        fits: ['Covers this postcode', 'Takes falls and frailty', 'Can respond inside 2 hrs'], watch: ['Visits after 18:00 need phone confirmation'] },
      { name: 'Hospital at home', type: 'Virtual beds', status: 'Over capacity', kind: 'surge', big: '+2', unit: 'over established capacity', travel: 'Review within about 3 hrs', age: '14 min ago',
        fits: ['Frailty pathway', 'Covers this postcode'], watch: ['Over capacity now. Phone to confirm before offering.'] },
      { name: 'Community hospital · Ward B', type: 'Inpatient beds', status: 'Accepting', kind: 'open', big: '5', unit: 'beds free', travel: '35 to 50 min by road', age: '2 hrs 10 min ago',
        fits: ['Rehab and frailty beds', 'Weight-bearing assessment on site'], watch: ['Admissions before 20:00 only', 'Data is over 2 hrs old. Consider phoning.'] }
    ];
    return {
      cards: cards.map((c) => ({
        ...c,
        isOpen: c.kind === 'open',
        isSurge: c.kind === 'surge',
        chipBg: c.kind === 'open' ? '#0B5C8C' : '#6B2C91',
        numColor: c.kind === 'open' ? '#0B3F61' : '#4B1C69',
        border: c.kind === 'open' ? '2px solid #DDE3E6' : '2px solid #6B2C91'
      }))
    };
  }
}

## Artboard: AdvisorPhone

Advisor on phone: options and service detail
Options
DIUCS capacity
On call 02:14
80+ · DT4 8XX · Fall, Frailty · Within 2 hrs · NEWS2 2 · CFS 6
[btn] Edit
3 services meet the criteria. Sorted by travel time.
UCR West
 Accepting
4
referrals in next 2 hrs
Visits patient, about 1 hr 20 · Updated 9 min ago
Hospital at home
 Over capacity
+2
over established capacity
Review within about 3 hrs · Updated 14 min ago
Community hospital · Ward B
 Accepting
5
beds free
35 to 50 min by road · Updated 2 hrs 10 min ago
[btn] Copy summary for SystmOne
Service detail
[btn] [Back to options] 
UCR West
4
referrals in next 2 hrs
 Accepting
 Reported by text at 14:03 · next due 14:30
Response time about 1 hr 20
Accepts
Falls without injury · Frailty · Age 18+ · Postcodes DT1 to DT4 · 08:00 to 20:00
Does not accept
Suspected fracture · Head injury on anticoagulants · Needs IV therapy
Criteria version 3 · last reviewed 12 Sep · review by 12 Dec · owner: UCR clinical lead
[btn] Request booking
[btn] I phoned
[btn] They declined

## Artboard: AdvisorScores

Advisor: score pickers
Score from the referrer · one picker per method
## NHS Pathways Dx
Used by 111 and ambulance telephone triage
Search Dx code or description[input text value='' placeholder='']
[btn] [Dx code] · [disposition description]
[btn] [Dx code] · [disposition description]
[btn] [Dx code] · [disposition description]
Choose from the list. Codes cannot be typed freely.
## Ambulance category
Used by 999
[btn] Category 1Life-threatening
[btn] Category 2Emergency
[btn] Category 3Urgent
[btn] Category 4Less urgent
Recorded as the crew gave it.
## Manchester triage
Used by emergency departments
[btn] Immediate
[btn] Very urgent
[btn] Urgent
[btn] Standard
[btn] Non-urgent
Only for referrers who have already triaged in an emergency department.
## NEWS2 and Clinical Frailty Scale
Wards, ambulance, frailty services
NEWS2 score (0 to 20)[input text value='2' placeholder='']
Clinical Frailty Scale (1 to 9)
[btn] 1
[btn] 2
[btn] 3
[btn] 4
[btn] 5
[btn] 6
[btn] 7
[btn] 8
[btn] 9
6 · Moderately frail
Scores are recorded as the referrer gave them. The tool does not calculate or check them.

## Artboard: AdvisorActions

Advisor: action dialogs
Advisor actions · dialogs
## I phoned
UCR West
What did UCR West tell you?
[btn] Accepting
[btn] Limited
[btn] Not accepting
How many can they take?[input text value='3' placeholder='']
[btn] Save position
[btn] Cancel
Updates the board for everyone. Recorded as “advisor phoned”.
## They declined
The board showed capacity
Why did UCR West decline?
[btn] Full, not yet reported
[btn] Outside their criteria
[btn] Staffing or transport
[btn] Other
[btn] Save
[btn] Cancel
For a conversation with the service. Not used to assess advisors.
## Ask a clinical advisor
Escalate
80+ · DT4 8XX · Fall, Frailty · Within 2 hrs
NEWS2 2 · Frailty scale 6 · Options shown: 3
How soon do you need them?
[btn] Now
[btn] Within 15 min
2 clinical advisors available
[btn] Call clinical advisor
[btn] Cancel
The case summary goes with the call. No name is sent.
## No service fits right now
Empty state
Every service is either not accepting, outside the criteria, or not updated.
What instead
[btn] Widen the time: today instead of within 2 hrs
[btn] Phone a service you know has space
[btn] Ask a clinical advisor
[btn] Other routes under local protocol
Never end the call on a refusal. Always offer a next step.

## Artboard: AdvisorFinish

Advisor: criteria, outcome and close
Finishing a call
## Criteria: UCR West
Full view
Accepts
Falls without injury · Frailty · Age 18+ · Postcodes DT1 to DT4 · 08:00 to 20:00
Does not accept
Suspected fracture · Head injury on anticoagulants · Needs IV therapy
Version 3 · reviewed 12 Sep · review by 12 Dec · owner: UCR clinical lead
[btn] Report a problem with these criteria
[btn] Close
## Record outcome
Reference 4821
What happened?
[btn] Accepted and booked
[btn] Declined
[btn] Redirected
[btn] Caller cancelled
If the best fit was not used, why?
[btn] Full
[btn] Declined
[btn] Data too old
[btn] Caller preference
[btn] Clinical override
[btn] Save outcome
[btn] Cancel
## Summary for SystmOne
Read-only. Paste into the referral.
Referrer
Ambulance crew
Age band
80+
Postcode
DT4 8XX
Needs
Fall, frailty
Urgency
Within 2 hrs
Scores
NEWS2 2 · Frailty scale 6
Destination
UCR West
Booked
Confirmed 14:19, reference 4821
Data age
Capacity 9 min old · criteria v3
[btn] Copy summary
[btn] Done
Copied to clipboard
## Call closed
Case closed
Reference 4821 is saved. The postcode has been cleared from this screen.
Kept for audit
Need category, age band, urgency, scores, destination, outcome, times, and what the board showed.
Cleared
Postcode.
[btn] Start next call
Retention periods are for IG to set.

## Artboard: AdvisorSteps

Advisor: step by step
1 Sign in (Trust account)
diucs.example/admin
DIUCS capacity
## Sign in
Use your Trust staff account. There is no new password.
[btn] Sign in with your Trust account
Having trouble? Ask your shift lead to check your access.
2 How a call works
diucs.example/admin
## How a call works
Every call has four steps. The screen always tells you which one you are on.
1
Needs
Age, postcode, what they need, how soon, any score
2
Options
Compare the services that fit. Check their criteria.
3
Request
Ask a service to take the patient. Wait for CONFIRMED.
4
Outcome
Record what happened. Copy the summary to SystmOne.
[btn] Try a practice call
[btn] Start a call
3 Step 2: Options
diucs.example/admin
Needs
2
Options
3
Request
4
Outcome
Now: compare the options and check the criteria.
Next: request a booking from the one you choose.
UCR West
Accepting
4
referrals in the next 2 hrs
[btn] Criteria
[btn] Request booking
Hospital at home
Over capacity
+2
over established capacity
[btn] Criteria
[btn] I phoned
4 Step 3: Request
diucs.example/admin
Needs
Options
3
Request
4
Outcome
Now: waiting for UCR West to confirm. Phone prompt at 14:21.
Next: when they confirm, tell the caller.
UCR West
Requested
—
Not booked yet
[btn] Phone them instead
[btn] Cancel request
5 Step 4: Outcome
diucs.example/admin
Needs
Options
Request
4
Outcome
Now: record what happened, then copy the summary.
Next: start the next call.
What happened?
[btn] Accepted and booked
[btn] Declined
[btn] Redirected
[btn] Caller cancelled
[btn] Copy summary for SystmOne
[btn] Save outcome

## Artboard: ClinicalAdvisor

Clinical advisor: step by step
1 Sign in
[btn] [Back] 
Sign in
## Clinical advisor sign in
Use your Trust staff account. There is no new password.
Clinical advisors see case details, so this uses staff sign-in, not a texted code.
[btn] Sign in with your Trust account
2 Go on duty
[btn] [Back] 
On duty
## Are you taking requests?
[btn] Available
[btn] Busy
[btn] Away
1 request waiting
2 clinical advisors available now
Advisors see how many of you are available. They see your name only after you take a request.
[btn] Save status
3 Alert
Friday 23 October
14:13
DDIUCS capacitynow
Clinical advice requested: now
80+, fall and frailty. Waiting 1 min.
4 Queue
[btn] [Back] 
Requests
[btn] Waiting (2)
[btn] Mine
[btn] Done
NowWaiting 1 min
80+ · fall and frailty · NEWS2 2 · frailty 6 · borderline criteria
[btn] Take it
Within 15 minWaiting 6 min
16 to 64 · wound care · caller unsure of urgency
[btn] Take it
Once you take a request, no one else can. It returns to the queue if you do not act in 10 minutes.
5 Review the case
[btn] [Back] 
Case 4821
The case
80+ · DT4 8XX · fall and frailty
Within 2 hrs · ambulance crew
NEWS2 2 · frailty scale 6
Why the advisor asked
Borderline criteria
What the advisor saw at 14:13
UCR West: accepting, 4, 9 min old
Hospital at home: over capacity, +2
Ward B: accepting, 5, 2 hrs 10 min old
[btn] Give advice
[btn] Call the advisor
6 Give advice
[btn] [Back] 
Your advice
What do you advise?
[btn] Go ahead with UCR West
[btn] Use another service
[btn] Needs a clinical call to the referrer
[btn] Send to the emergency route under local protocol
Why? (optional)
[btn] Within criteria on my judgement
[btn] Safer alternative
[btn] Other
Add a short note only if needed. No patient names.
[btn] Send advice
[btn] Cancel
7 Sent and logged
[btn] [Back] 
Advice sent
## Advice sent
The advisor has it now. Logged for audit: your role, the time, your advice and what you saw.
Clinical overrides are reviewed with the service leads, not used to assess advisors.
[btn] Next request
[btn] Go off duty

## Artboard: ShiftLead

Shift lead: who needs chasing
DIUCS capacity · Shift lead
Friday 23 October · 14:12 · Sample data
## 2 services need chasing
Virtual ward · frailty
Report was due 12:00. Overdue by 2 hrs 12 min. Last figure: 3 beds free.
 Shown as unknown on the board
12:00
Text sent. Done.
12:30
Reminder sent. Done.
13:00
Advisor phone task. Not done.
13:30
Escalated to you.
[btn] Enter what they told me by phone
[btn] Send reminder again
[btn] Change number
Community hospital · Ward A
Reported 2 hrs 10 min ago. Next due 17:00. On schedule, but the figure is getting old.
 Limited
[btn] Ask for an update now
## Covering today
Reports go to a registered number. Change it for leave or cover.
UCR East · number ending 4821 · cover until 20:00
[btn] Change number
Reablement · number ending 0377 · usual contact
[btn] Change number
## System now
Accepting4
Limited2
Not accepting1
Over capacity1
Not updated1
9 services reporting today
## Criteria to review
Community hospital · Ward A
Version 2 · review by 30 Oct (7 days)
SDEC · Site 1
Version 4 · review by 18 Nov (26 days)
[btn] Send review reminder to owners
## Declined despite showing capacity today
2 cases, both at Community hospital · Ward A.
For a conversation with the service, not a league table. Not used to assess advisors.

## Artboard: ShiftLeadFlows

Shift lead: admin flows
Shift lead · admin flows
## Change reporter number
Cover for leave
Service[input text value='UCR East' placeholder='']
Current number ends 4821
New mobile number[input text value='07700 900456' placeholder='']
How long?
[btn] Today
[btn] This week
[btn] Until I change it
[btn] Send a test text
[btn] Save
The old number stops working as soon as you save. Both numbers are logged.
## Review criteria change
UCR West
Was Age 18+
Now Age 16+
Version 3 to version 4 · owner: UCR clinical lead · review by 12 Mar
[btn] Approve and publish
[btn] Send back
[btn] Cancel
Advisors see the new version only after you publish. The old version stays in the audit record.
## What the advisor saw
Audit replay
Reference 4821 · 23 Oct 14:13:20
UCR West Accepting, 4, 9 min old
Hospital at home Over capacity, +2, 14 min old
Community hospital · Ward B Accepting, 5, 2 hrs 10 min old
Criteria version 3
14:12
Case 4821 opened
14:13
Three options shown
14:16
Booking request sent to UCR West
14:19
Confirmed by text
[btn] Export for review
Read-only. Opened for audit, with a log of who looked.
## Add a service reporter
Onboarding
Service name[input text value='[Service name]' placeholder='']
Unit label[input text value='[referrals in the next 2 hrs]' placeholder='']
Channel
[btn] Text
[btn] Email
Mobile number[input text value='[07xxx xxxxxx]' placeholder='']
Usual cadence
[btn] Every 2 hrs
[btn] Twice a day
[btn] Once a day
[btn] Send a test prompt
[btn] Save
Services with neither text nor email are outside the MVP.

## Artboard: ShiftLeadPhone

Shift lead on phone: admin flows
Change reporter number
[btn] [Back] 
Change number
Service[input text value='UCR East' placeholder='']
Current number ends 4821
New mobile number[input text value='07700 900456' placeholder='']
How long?
[btn] Today
[btn] This week
[btn] Until I change it
The old number stops working when you save. Both numbers are logged.
[btn] Send a test text
[btn] Save
Review criteria
[btn] [Back] 
Review criteria
UCR West
Was Age 18+
Now Age 16+
Version 3 to version 4 · owner: UCR clinical lead · review by 12 Mar
Advisors see the new version only after you publish. The old version stays in the audit record.
[btn] Approve and publish
[btn] Send back
[btn] Cancel
Audit replay
[btn] [Back] 
What the advisor saw
Reference 4821 · 14:13:20
UCR West Accepting, 4, 9 min old
Hospital at home Over capacity, +2, 14 min old
Ward B Accepting, 5, 2 hrs 10 min old
Criteria version 3
14:12
Case 4821 opened
14:13
Three options shown
14:16
Request sent to UCR West
14:19
Confirmed by text
Read-only. Opened for audit, with a log of who looked.
[btn] Export for review
Add a service reporter
[btn] [Back] 
Add reporter
Service name[input text value='[Service name]' placeholder='']
Unit label[input text value='[referrals in the next 2 hrs]' placeholder='']
Channel
[btn] Text
[btn] Email
Mobile number[input text value='[07xxx xxxxxx]' placeholder='']
Usual cadence
[btn] Every 2 hrs
[btn] Twice a day
[btn] Send a test prompt
[btn] Save

## Artboard: ShiftLeadInvite

Shift lead: invite and track a reporter
1 Invite a reporter
diucs.example/admin
## Invite a service reporter
ServiceRequired[input text value='UCR West' placeholder='']
RoleRequired[input text value='[Role, for example duty manager]' placeholder='']
Mobile numberRequired
A ward or team phone is best[input text value='[07xxx xxxxxx]' placeholder='']
Suggest how they reportRequired
They can change this during set-up.
[btn] App notification
[btn] Text
[btn] Email
The text we send
DIUCS: You are invited to report capacity for UCR West. Set up takes about 3 minutes: diucs.example/i/… Valid for 48 hrs.
[btn] Send invitation
[btn] Cancel
2 Track set-up
diucs.example/admin
## Set-up progress
UCR East · [Role]
Invited
Number checked
Channel chosen
Installed
Notifications on
PIN set
First report
Stuck at: Notifications on. Invited 09:00, last seen 09:21.
[btn] Resend invitation
[btn] Switch them to text
[btn] Phone them
Reablement · [Role]
Invited
Number checked
Channel chosen
Installed
Notifications on
PIN set
First report
Complete. First report 10:12.

## Artboard: ScreenPairing

Wall screen set-up
1 On the wall display
diucs.example/screen
DIUCS capacity wall screen
482 913
Enter this code in the admin page to connect this screen.
Waiting to be connected · code works for 10 minutes
2 In the admin page
diucs.example/admin
## Add a wall screen
Code shown on the screenRequired[input text value='482 913' placeholder='']
Screen nameRequired[input text value='[Screen name]' placeholder='']
Where it isOptional[input text value='[Room or area]' placeholder='']
This screen will show capacity only. It never shows patient information.
[btn] Connect screen
[btn] Cancel
3 Connected
diucs.example/admin
## Screen connected
[Screen name] is now showing the live board.
StatusOnline, updated 14:12
ShowsCapacity only. No patient information.
If it goes offlineThe board shows Last known and says so
[btn] Add another screen
[btn] Done

## Artboard: RegisterFlow1

Register a service: sign in to location
1 Sign in
diucs.example/register
DIUCS capacity
## Register your service
Enter your mobile number. We text you a code to check it is you.
Mobile numberRequired
Use the number your invitation was sent to[input text value='[07xxx xxxxxx]' placeholder='']
[btn] Send code
You need an invitation from the SPOA shift lead to register. Check your texts or email for the link.
Having trouble? Ask the SPOA shift lead to check your invitation.
2 Start: what you need
diucs.example/register
## Register a service
It takes about 10 minutes. Have these ready:
Organisation name and ODS code
The address of the site, or the area you cover
A phone number the SPOA can call
Who owns your criteria, and when they are next reviewed
A mobile number or email for capacity updates
[btn] Start
[btn] Save and come back later
Drafts are saved as you go. Nothing is live until the SPOA shift lead approves it.
3 Step 1: Organisation
diucs.example/register
Step 1 of 5 · Organisation
## Tell us about your organisation
Organisation nameRequired
As it appears on the NHS ODS register[input text value='[Organisation name]' placeholder='']
ODS codeRequired
The organisation code from the NHS ODS register[input text value='[ODS code]' placeholder='']
Organisation typeRequired
[btn] NHS trust
[btn] GP practice
[btn] Local authority
[btn] Voluntary or independent
[btn] Other
Part of a larger organisationOptional[input text value='[Parent organisation]' placeholder='']
Contact nameRequired[input text value='[Name]' placeholder='']
Contact roleOptional[input text value='[Role]' placeholder='']
Contact email or phoneRequired
For the SPOA to reach your organisation about this registration[input text value='[Email or phone]' placeholder='']
[btn] Continue
[btn] Back
[btn] Save draft
4 Step 2: Location
diucs.example/register
Step 2 of 5 · Location
## Where is the service?
Do you have a fixed site?Required
Choose No for services that visit patients, such as community response or virtual wards. You will add the area you cover in step 3.
[btn] Yes, a building or ward
[btn] No, we visit patients
PostcodeRequired[input text value='[Postcode]' placeholder='']
[btn] Find address
Choose the address
[btn] [Address line 1], [town], [postcode]
[btn] [Address line 1], [town], [postcode]
[btn] [Address line 1], [town], [postcode]
Position found from the address. You do not need to enter coordinates.
Site nameRequired[input text value='[Ward or site name]' placeholder='']
Site typeRequired
[btn] Ward
[btn] Community hospital
[btn] Hub or base
[btn] Clinic
[btn] Other
Opening hoursRequired
[btn] Mon
[btn] Tue
[btn] Wed
[btn] Thu
[btn] Fri
[btn] Sat
[btn] Sun
[btn] 24 hours
OpensRequired[input text value='08:00' placeholder='']
ClosesRequired[input text value='20:00' placeholder='']
Site ODS codeOptional[input text value='[Site code]' placeholder='']
[btn] Continue
[btn] Back
[btn] Save draft

## Artboard: RegisterFlow2

Register a service: service to review
5 Step 3: Service
diucs.example/register
Step 3 of 5 · Service
## Describe the service
Service nameRequired
The name advisors see, for example “UCR West”[input text value='[Service name]' placeholder='']
CategoryRequired
[btn] Urgent community response
[btn] Same day emergency care
[btn] Inpatient beds
[btn] Hospital at home or virtual ward
[btn] Reablement
[btn] Urgent treatment
[btn] Mental health crisis
[btn] Other
SpecialtyOptional[input text value='[Specialty]' placeholder='']
How can the SPOA refer?Required
[btn] Phone
[btn] SystmOne
[btn] Email
[btn] e-Referral
Phone number for the SPOA to callRequired
Staffed while you accept referrals[input text value='[Phone number]' placeholder='']
Days you accept referralsRequired
[btn] Mon
[btn] Tue
[btn] Wed
[btn] Thu
[btn] Fri
[btn] Sat
[btn] Sun
FromRequired[input text value='08:00' placeholder='']
ToRequired[input text value='20:00' placeholder='']
## Who it is for
Needs you acceptRequired
[btn] Fall, no injury
[btn] Frailty
[btn] Wound care
[btn] IV therapy
[btn] Palliative
[btn] Dementia
Youngest ageRequired[input text value='18' placeholder='']
Oldest ageRequired[input text value='No limit' placeholder='']
Needs you do not acceptRequired
[btn] Suspected fracture
[btn] Head injury on anticoagulants
[btn] Needs IV therapy
[btn] Infection isolation
[btn] No exclusions
Criteria owner (role)Required[input text value='[Role]' placeholder='']
Owner emailRequired[input text value='[Email]' placeholder='']
Review criteria byRequired
Advisors see a flag when this date passes[input text value='[Date]' placeholder='']
Area you cover (postcode districts)Required
Required if you visit patients
[btn] DT1
[btn] DT2
[btn] DT3
[btn] DT4
[btn] Add district
Appointment needed?Optional
[btn] Yes
[btn] No
Anything else advisors should knowOptional[input text value='' placeholder='']
[btn] Continue
[btn] Back
[btn] Save draft
6 Step 3: with errors
diucs.example/register
Step 3 of 5 · Service
## Describe the service
There are 3 problemsChoose a categoryEnter a phone number the SPOA can callEnter who owns the criteria
Service nameRequired[input text value='UCR West' placeholder='']
CategoryRequired
[btn] Urgent community response
[btn] Same day emergency care
[btn] Inpatient beds
[btn] Hospital at home or virtual ward
[btn] Reablement
[btn] Urgent treatment
[btn] Mental health crisis
[btn] Other
Choose a category
Phone number for the SPOA to callRequired[input text value='0123' placeholder='']
Enter a full phone number, for example [01xxx xxxxxx]
Criteria owner (role)Required[input text value='' placeholder='']
Enter who owns the criteria
[btn] Continue
[btn] Back
[btn] Save draft
7 Step 4: Capacity reporting
diucs.example/register
Step 4 of 5 · Capacity reporting
## How will you report capacity?
What do you count?Required
[btn] Referrals in the next 2 hrs
[btn] Beds free
[btn] Slots left today
[btn] Packages available
[btn] Virtual beds free
[btn] Other
Lowest usual numberRequired[input text value='0' placeholder='']
Highest usual numberRequired[input text value='8' placeholder='']
How often do you report?Required
[btn] Every 2 hrs
[btn] Twice a day
[btn] Once a day
How will you report?Required
App notification needs the app on your home screen. Services that can do none of these are outside the pilot.
[btn] App notification
[btn] Text
[btn] Email
Mobile number for textRequired
A ward or team phone is best. It stays with the post, not the person.[input text value='[07xxx xxxxxx]' placeholder='']
Who holds this phoneRequired[input text value='[Role, for example duty manager]' placeholder='']
Cover numberOptional[input text value='[07xxx xxxxxx]' placeholder='']
Types of bed or slot you reportOptional
[btn] Women only
[btn] Men only
[btn] Side room
[btn] Rehab
[btn] Palliative
Does your system have an API?Optional
Not used in the pilot. If you answer Yes, we ask for the details below and keep them for later.
[btn] No
[btn] Yes
If you answered Yes
API nameRequired[input text value='[Name]' placeholder='']
API addressRequired[input text value='[https://…]' placeholder='']
Connection typeRequired[input text value='[Type]' placeholder='']
Type of dataRequired[input text value='[Type of data]' placeholder='']
[btn] Continue
[btn] Back
[btn] Save draft
8 Step 5: Review and submit
diucs.example/register
Step 5 of 5 · Review
## Check your details
Organisation
Complete
[Organisation name] · ODS [code] · NHS trust
[btn] Change
Location
Complete
[Site name] · [address] · Mon to Fri 08:00 to 20:00
[btn] Change
Service
Needs attention
UCR West · Urgent community response · refer by phone and SystmOne · criteria review date missing
[btn] Change
Capacity reporting
Complete
Referrals in the next 2 hrs · usual range 0 to 8 · every 2 hrs · text to [role]
[btn] Change
API
Complete
Not provided. You can add this later.
[btn] Change
The SPOA shift lead checks your details and sends a test text. You will not appear on the board until approved.
[btn] Submit for approval
[btn] Back
[btn] Save draft

## Artboard: RegisterFlow3

Register a service: approval and my services
9 Submitted
diucs.example/register
## Submitted for approval
The SPOA shift lead will check your details and send a test text to the number you gave. Expected time: [expected time].
You will get an email when it is approved, or if something needs changing.
[btn] Back to my services
10 Shift lead: approve
diucs.example/admin
## 2 registrations to review
UCR East
Submitted by [Name], [Role] · [organisation]
Organisation code checked
ODS code found on the register
Address found
Position set from the postcode
Test text answered
Sent 14:02, no reply yet
Criteria owner confirmed
Email not yet confirmed
[btn] Send test text again
[btn] Approve
[btn] Send back with a note
Reablement
[btn] Review
11 My services
diucs.example/register
## My services
UCR West
Active
Reporting every 2 hrs by text
[btn] Edit
[btn] Pause reporting
Reablement
Pending approval
Submitted 23 Oct
[btn] Edit
[btn] Pause reporting
Community hospital · Ward A
Review due
Criteria review due 30 Oct
[btn] Edit
[btn] Pause reporting
[btn] Register another service

## Artboard: RegisterModel

Registration fields and FHIR R4
Registration fields and FHIR R4
Draft for the data model. Not shown in the UI.
Registration fields mapped to FHIR R4 elements
Group | Screen field | FHIR R4 element | In base R4 | In our profile | Note | 
Organisation | Organisation name | Organization.name | 0..1 (name or identifier needed) | Required | | 
Organisation | ODS code | Organization.identifier | 0..* | Required | Confirm the ODS identifier system URI before use | 
Organisation | Organisation type | Organization.type | 0..* | Required | | 
Organisation | Part of | Organization.partOf | 0..1 | Optional | | 
Organisation | Main contact | Organization.contact (name, telecom) | 0..* | Required, one | Contact for registration, not for patients | 
Organisation | Active | Organization.active | 0..1 | Set on approval | | 
Location | Site name | Location.name | 0..1 | Required | | 
Location | Address | Location.address | 0..1 | Required for a fixed site | Postcode lookup returns a list to pick from | 
Location | Position | Location.position.latitude, longitude | 1..1 inside position | Set from the address | From the OS Places lookup. Keep the UPRN as Location.identifier | 
Location | Site type | Location.type, Location.physicalType | 0..*, 0..1 | Required | | 
Location | Opening hours | Location.hoursOfOperation | 0..* | Required, or 24 hours | | 
Location | Managed by | Location.managingOrganization | 0..1 | Required | Defaults to the organisation | 
Location | Status | Location.status | 0..1 | Set on approval | | 
Service | Service name | HealthcareService.name | 0..1 | Required | | 
Service | Provided by | HealthcareService.providedBy | 0..1 | Required | Set from step 1 | 
Service | Category | HealthcareService.category | 0..* | Required | Matches the capacity unit table | 
Service | Specialty | HealthcareService.specialty | 0..* | Optional | | 
Service | Site(s) | HealthcareService.location | 0..* | Required unless area based | | 
Service | Area covered | HealthcareService.coverageArea | 0..* | Required if visiting | Needs Location resources that stand for areas, such as postcode districts | 
Service | How to refer | HealthcareService.referralMethod | 0..* | Required | | 
Service | SPOA phone | HealthcareService.telecom (phone) | 0..* | Required | | 
Service | Hours accepting referrals | HealthcareService.availableTime | 0..* | Required | Can differ from site opening hours | 
Service | Planned closures | HealthcareService.notAvailable | 0..* | Optional | | 
Service | Who it is for | HealthcareService.eligibility | 0..* | Required | Holds a coded need plus a comment | 
Service | Who it is not for | Local extension | Not in base R4 | Required, or No exclusions | Needed for filtering on hard exclusions | 
Service | Criteria owner, version, review-by date | Local extension | Not in base R4 | Required | Drives the stale-criteria flag | 
Service | Appointment needed | HealthcareService.appointmentRequired | 0..1 | Optional | | 
Service | Active | HealthcareService.active | 0..1 | Set on approval | | 
Capacity | Unit label, usual range, cadence, channel | Local extension | Not in base R4 | Required | Not part of HealthcareService | 
Capacity | Reporting contact (role phone or email) | Local extension or a separate record | Not in base R4 | Required | Personal data. Keep apart from the service record that other systems can read | 
Capacity | Capacity values | Not on HealthcareService | Not in base R4 | Not entered here | A time series with age and source. Use Observation or your own table | 
API | API details | Endpoint: status, connectionType, payloadType, address | 1..1, 1..1, 1..*, 1..1 | Only if the service has an API | Linked from HealthcareService.endpoint | 
## Base R4 requires almost nothing
HealthcareService and Location have no required elements, and Organization needs only a name or identifier. The “Required” column is our own profile, so we define and publish it. Check the NHS Directory of Services and UK Core first, so we reuse them where they fit.
## Patient postcodes stay local
Locations are geocoded once, at registration, with OS Places. A patient’s postcode should not go to an outside API on every call. Use a postcode centroid dataset hosted in the Trust. Check OS licensing for NHS use.
## Capacity is not a service attribute
HealthcareService has no bed or slot count. Counts change every few hours and must carry their age and source, so keep them as a time series linked to the service, and use extensions only for the unit label and range.

## Artboard: RegisterMobile

Register a service on mobile
1 Start
[btn] [Back] 
Register a service
## Register a service
It takes about 10 minutes. Have these ready:
Organisation name and ODS code
The address of the site, or the area you cover
A phone number the SPOA can call
Who owns your criteria, and when they are next reviewed
A mobile number or email for capacity updates
[btn] Start
[btn] Save and come back later
Drafts are saved as you go. Nothing is live until the SPOA shift lead approves it.
2 Organisation
[btn] [Back] 
Step 1 of 5 · Organisation
## Tell us about your organisation
Organisation nameRequired
As it appears on the NHS ODS register[input text value='[Organisation name]' placeholder='']
ODS codeRequired
The organisation code from the NHS ODS register[input text value='[ODS code]' placeholder='']
Organisation typeRequired
[btn] NHS trust
[btn] GP practice
[btn] Local authority
[btn] Voluntary or independent
[btn] Other
Part of a larger organisationOptional[input text value='[Parent organisation]' placeholder='']
Contact nameRequired[input text value='[Name]' placeholder='']
Contact roleOptional[input text value='[Role]' placeholder='']
Contact email or phoneRequired
For the SPOA to reach your organisation about this registration[input text value='[Email or phone]' placeholder='']
[btn] Continue
[btn] Save draft
[btn] Back
3 Location
[btn] [Back] 
Step 2 of 5 · Location
## Where is the service?
Do you have a fixed site?Required
Choose No for services that visit patients. You add the area you cover in step 3.
[btn] Yes, a building or ward
[btn] No, we visit patients
PostcodeRequired[input text value='[Postcode]' placeholder='']
[btn] Find address
Choose the address
[btn] [Address line 1], [town], [postcode]
[btn] [Address line 1], [town], [postcode]
[btn] [Address line 1], [town], [postcode]
Position found from the address.
Site nameRequired[input text value='[Ward or site name]' placeholder='']
Site typeRequired
[btn] Ward
[btn] Community hospital
[btn] Hub or base
[btn] Clinic
[btn] Other
Opening hoursRequired
[btn] Mon
[btn] Tue
[btn] Wed
[btn] Thu
[btn] Fri
[btn] Sat
[btn] Sun
[btn] 24 hours
OpensRequired[input text value='08:00' placeholder='']
ClosesRequired[input text value='20:00' placeholder='']
Site ODS codeOptional[input text value='[Site code]' placeholder='']
[btn] Continue
[btn] Save draft
[btn] Back
4 Service
[btn] [Back] 
Step 3 of 5 · Service
## Describe the service
Service nameRequired
The name advisors see, for example “UCR West”[input text value='[Service name]' placeholder='']
CategoryRequired
[btn] Urgent community response
[btn] Same day emergency care
[btn] Inpatient beds
[btn] Hospital at home or virtual ward
[btn] Reablement
[btn] Urgent treatment
[btn] Mental health crisis
[btn] Other
SpecialtyOptional[input text value='[Specialty]' placeholder='']
How can the SPOA refer?Required
[btn] Phone
[btn] SystmOne
[btn] Email
[btn] e-Referral
Phone number for the SPOA to callRequired
Staffed while you accept referrals[input text value='[Phone number]' placeholder='']
Days you accept referralsRequired
[btn] Mon
[btn] Tue
[btn] Wed
[btn] Thu
[btn] Fri
[btn] Sat
[btn] Sun
FromRequired[input text value='08:00' placeholder='']
ToRequired[input text value='20:00' placeholder='']
## Who it is for
Needs you acceptRequired
[btn] Fall, no injury
[btn] Frailty
[btn] Wound care
[btn] IV therapy
[btn] Palliative
[btn] Dementia
Youngest ageRequired[input text value='18' placeholder='']
Oldest ageRequired[input text value='No limit' placeholder='']
Needs you do not acceptRequired
[btn] Suspected fracture
[btn] Head injury on anticoagulants
[btn] Needs IV therapy
[btn] Infection isolation
[btn] No exclusions
Criteria owner (role)Required[input text value='[Role]' placeholder='']
Owner emailRequired[input text value='[Email]' placeholder='']
Review criteria byRequired
Advisors see a flag when this date passes[input text value='[Date]' placeholder='']
Area you cover (postcode districts)Required
Required if you visit patients
[btn] DT1
[btn] DT2
[btn] DT3
[btn] DT4
[btn] Add district
Appointment needed?Optional
[btn] Yes
[btn] No
Anything else advisors should knowOptional[input text value='' placeholder='']
[btn] Continue
[btn] Save draft
[btn] Back
5 Capacity reporting
[btn] [Back] 
Step 4 of 5 · Capacity reporting
## How will you report capacity?
What do you count?Required
[btn] Referrals in the next 2 hrs
[btn] Beds free
[btn] Slots left today
[btn] Packages available
[btn] Virtual beds free
[btn] Other
Lowest usual numberRequired[input text value='0' placeholder='']
Highest usual numberRequired[input text value='8' placeholder='']
How often do you report?Required
[btn] Every 2 hrs
[btn] Twice a day
[btn] Once a day
How will you report?Required
App notification needs the app on your home screen. Services that can do none of these are outside the pilot.
[btn] App notification
[btn] Text
[btn] Email
Mobile numberRequired
A ward or team phone is best. It stays with the post, not the person.[input text value='[07xxx xxxxxx]' placeholder='']
Who holds this phoneRequired[input text value='[Role, for example duty manager]' placeholder='']
Cover numberOptional[input text value='[07xxx xxxxxx]' placeholder='']
Types of bed or slot you reportOptional
[btn] Women only
[btn] Men only
[btn] Side room
[btn] Rehab
[btn] Palliative
Does your system have an API?Optional
Not used in the pilot. If Yes, we ask for the details and keep them for later.
[btn] No
[btn] Yes
[btn] Continue
[btn] Save draft
[btn] Back
6 Review
[btn] [Back] 
Step 5 of 5 · Review
## Check your details
Organisation
Complete
[Organisation name] · ODS [code]
[btn] Change
Location
Complete
[Site name] · Mon to Fri 08:00 to 20:00
[btn] Change
Service
Needs attention
UCR West · refer by phone and SystmOne · criteria review date missing
[btn] Change
Capacity reporting
Complete
Referrals in the next 2 hrs · every 2 hrs · app notification
[btn] Change
API
Complete
Not provided. Add later.
[btn] Change
The SPOA shift lead checks your details and sends a test notification. You will not appear on the board until approved.
[btn] Submit for approval
[btn] Save draft
[btn] Back
7 Submitted
[btn] [Back] 
Submitted
## Submitted for approval
The SPOA shift lead will check your details and send a test notification to the phone you gave. Expected time: [expected time].
You will get a notification when it is approved, or if something needs changing.
[btn] Back to my services
8 Step 3 with errors
[btn] [Back] 
Step 3 of 5 · Service
## Describe the service
There are 3 problemsChoose a categoryEnter a phone number the SPOA can callEnter who owns the criteria
Service nameRequired[input text value='UCR West' placeholder='']
CategoryRequired
[btn] Urgent community response
[btn] Same day emergency care
[btn] Inpatient beds
[btn] Hospital at home or virtual ward
[btn] Reablement
[btn] Urgent treatment
[btn] Mental health crisis
[btn] Other
Choose a category
Phone number for the SPOA to callRequired[input text value='0123' placeholder='']
Enter a full phone number
Criteria owner (role)Required[input text value='' placeholder='']
Enter who owns the criteria
[btn] Continue
[btn] Save draft
[btn] Back

## Artboard: ApprovalApplicant

Registration approval: applicant
1 Step 1, filled from your invitation
[btn] [Back] 
Step 1 of 5 · Organisation
## Your organisation
Service
UCR East
From your invitation. It cannot be changed.
Organisation
[Organisation name]
ODS code
[ODS code]
Your nameRequired[input text value='[Name]' placeholder='']
Your roleRequired[input text value='[Role]' placeholder='']
Not your service, or the details are wrong? Tell the SPOA shift lead. Do not carry on.
[btn] Continue
[btn] This is not my service
2 Submitted
[btn] [Back] 
Registration
## Submitted. We are checking.
Submitted
23 Oct 14:30
Checks
In progress. The SPOA shift lead may phone your service.
Approval
Test notification
Live
We aim to review within [time]. We will tell you by notification.
[btn] Back to my services
3 Needs changes
[btn] [Back] 
Needs changes
Needs changes
## A few things to fix
1. The criteria owner email must be an organisation address.
2. Add a cover number.
From [Name], SPOA shift lead, 14:52.
[btn] Fix and resubmit
[btn] Phone the shift lead
4 Approved: one last step
[btn] [Back] 
Approved
Approved
## One last step: a test
We send a test notification to your phone. Answer it as you normally would. This proves you receive and answer prompts.
You are not on the board until the test is answered.
[btn] Send my test notification
5 You are live
[btn] [Back] 
Live
## You are live
The SPOA can now see UCR East on the board. Your first prompt arrives at 16:00.
UCR East
How it looks on the board
Accepting
[btn] Go to the app
6 Not approved
[btn] [Back] 
Not approved
## We cannot add this service yet
Reason: outside the scope of the pilot.
You do not need to do anything. We will contact you if the scope changes.
You can ask for a review if you think this is wrong.
[btn] Ask for a review
[btn] Close
7 Confirm your details
[btn] [Back] 
Confirm details
## Are these still right?
We ask every [period], and whenever your reporting phone changes.
ServiceUCR East
Phone for the SPOA[Phone number]
Criteria owner[Role]
Reporting phone07xxx xxx456
If the reporting phone changes, the SPOA shift lead phones your service before the new phone goes live.
[btn] All correct
[btn] Something changed

## Artboard: ApprovalWeb1

Registration approval: reviewer, part 1
1 Services in scope
diucs.example/admin
## Services in scope
You can only invite services on this list.
UCR West
Urgent community response
In pilotLive
UCR East
Urgent community response
In pilotIn review
SDEC · Site 1
Same day emergency care
In pilot
[btn] Invite
Reablement
Care packages
LaterNot invited
[Private provider]
Not on the Dorset pathway
Out of scope
[btn] Add a service to the scope list
2 The queue
diucs.example/admin
## Registrations
[btn] To review (2)
[btn] Waiting (1)
[btn] Go live (1)
[btn] Done
UCR East
In review
Submitted 14:30 by [Role]
Criteria owner email is not an organisation address
[btn] Review
SDEC · Site 1
In review
Submitted 13:05 by [Role]
[btn] Review
3 Review overview
diucs.example/admin
Registered by [Name], [Role]
## UCR East
Checks the system did
ODS code found, active, NHS trust
Matches the name entered
Address found, in Dorset
Reporting phone is the one we invited
Criteria owner email is not an organisation address
Ask for an organisation address
Checks you do
1 Call back the service
Not done
2 Decide if it is in scope
Not done
3 Criteria second approval
Waiting for the clinical lead
4 Decide
Opens when 1 to 3 are done
[btn] Start with the call-back
4 Check 1: call back
diucs.example/admin
Check 1 of 4
## Call the service back
Phone the number on the NHS register or the Dorset directory. Do not use the number the applicant gave.
Number to call: [number from the register]
Number the applicant gave: [number]
What to say
1
Ask for [Name], or the person in charge
2
Ask: is [Name] a [Role] at UCR East?
3
Ask: did they register for DIUCS capacity today?
4
Do not talk about any patient
Result
[btn] Confirmed
[btn] Not confirmed
[btn] No answer
Who you spoke to (role)Required[input text value='[Role]' placeholder='']
[btn] Save result
[btn] Back
No answer? Try again, or ask the applicant for their line manager to confirm by email.

## Artboard: ApprovalWeb2

Registration approval: reviewer, part 2
5 Check 2: in scope?
diucs.example/admin
Check 2 of 4
## Is it in scope?
Is the service part of the Dorset urgent care pathway?
[btn] Yes
[btn] No
[btn] Not sure
Does it take referrals from the SPOA?
[btn] Yes
[btn] No
[btn] Not sure
Can it report by app, text or email?
[btn] Yes
[btn] No
[btn] Not sure
Is its category on the pilot list?
[btn] Yes
[btn] No
[btn] Not sure
Your decision
[btn] In scope: pilot
[btn] In scope: later
[btn] Out of scope
Reason (needed if not the pilot)Optional[input text value='' placeholder='']
[btn] Save
[btn] Back
6 Check 4: decide
diucs.example/admin
Check 4 of 4
## Decide
Before you can approve
Automatic checks passed or explained
Call-back done
Scope decided
Criteria second approval (waiting for the clinical lead)
[btn] Approve (not yet available)
Note to the applicantOptional
Needed to send back or not approve. No patient information.[input text value='' placeholder='']
[btn] Send back with a note
[btn] Not approved: out of scope
7 Second approval: clinical lead
diucs.example/admin
Second approval · SPOA clinical lead
## UCR East criteria
Accepts
Falls without injury · Frailty · Age 16+ · Postcodes DT3 to DT4 · 08:00 to 20:00
Does not accept
Suspected fracture · Head injury on anticoagulants
Owner: [Role] · review by [date] · version 1
Are these safe for advisors to rely on?
[btn] Yes, approve
[btn] A change is needed
Note (if a change is needed)Optional[input text value='' placeholder='']
[btn] Submit my decision
[btn] Back
8 Go live and record
diucs.example/admin
## Go live: UCR East
Approved by [Role] and [Role]
Test notification sent 16:02
Test answered 16:03 from the registered phone
UCR East
Board preview
Accepting
[btn] Set live
[btn] Back
Registration record
14:30Submitted by [Role]
14:41Call-back confirmed by [Role]
14:55Scope: pilot, by [Role]
15:20Criteria approved by [Role]
16:03Test answered
16:05Set live by [Role]
[btn] Export record

## Artboard: ApprovalPhone

Registration approval: reviewer on phone
1 Queue
[btn] [Back] 
Registrations
[btn] To review (2)
[btn] Waiting (1)
[btn] Go live (1)
UCR East
In review
Submitted 14:30
Criteria owner email is not an organisation address
[btn] Review
SDEC · Site 1
In review
2 Checks
[btn] [Back] 
UCR East
ODS code found, active
Address found, in Dorset
Reporting phone is the one invited
Criteria owner email
Not an organisation address
1 Call back
Not done
2 In scope?
Not done
3 Second approval
Waiting
[btn] Start the call-back
3 Call back
[btn] [Back] 
Call back
Check 1 of 4
Call: [number from the register]
Not the applicant’s number
1
Ask for [Name]
2
Is [Name] a [Role] at UCR East?
3
Did they register today?
4
No talk of patients
Result
[btn] Confirmed
[btn] Not confirmed
[btn] No answer
[btn] Call [number]
[btn] Save result
4 Decide
[btn] [Back] 
Decide
Automatic checks explained
Call-back done
Scope decided
Criteria second approval
[btn] Approve (not yet available)
[btn] Send back with a note
[btn] Not approved

## Artboard: ApprovalStates

Registration approval: states and controls
Registration approval
Make sure the service signing up is the service in scope.
## States
Registration states
State | Meaning | Who moves it on | The person is told | Target time | 
Invited | An invitation was sent for an in-scope service | Applicant registers | Text with link | 48 hrs to use | 
Draft | Applicant is filling it in | Applicant submits | — | — | 
Submitted | Waiting for a reviewer | Shift lead starts the checks | “We have it” | [time] | 
In review | Checks running | Shift lead and clinical lead | — | [time] | 
Needs changes | A note was sent back | Applicant resubmits | The note, by their chosen channel | [time] | 
Approved, not live | Checks and both approvals done | Applicant answers the test | “One last step: a test” | — | 
Live | On the board | Pause, or re-verification due | “You are live”, then the first prompt | — | 
Not approved | Out of scope or failed a check | Shift lead can reopen | The reason | — | 
Paused | Service closed for a period | Service or shift lead resumes | — | — | 
Re-verify due | Every [period], or the reporting phone changed | Applicant confirms. For a new phone, the shift lead calls back first | “Confirm your details” | [period] | 
## What each control stops
Someone pretends to be a service (F18)
Invitation only, and only for services on the scope list. The mobile is locked to the invitation. The ODS code is checked. The reviewer calls the register number back. A test notification must be answered. The criteria need a second approval.
A new phone or a new owner takes over
Re-verification every [period]. A changed reporting phone is not live until the shift lead calls back.
Wrong criteria go live (F7, F11)
The criteria owner and a clinical lead both approve. Criteria carry a review-by date.
An out-of-scope service appears on the board
A scope list, with the decision and reason recorded.
A reviewer misses a step
Approve stays unavailable until every check is done, and says what is missing.
Nobody can show who approved what
Every step is logged with who, when and what they saw. The record can be exported.
## Decisions we need
Who the approvers are. Which role gives the second approval of criteria. Time targets for each state. The re-verification period. What counts as in scope. What to do if the call-back cannot be completed.

## Artboard: CriteriaOwner

Criteria owner: review, change and approve
1 Reminder
Friday 23 October
09:00
DDIUCS capacitynow
UCR West criteria: review due
Due 12 Dec. Confirm or update in 2 minutes.
2 Review overview
[btn] [Back] 
UCR West criteria
Version 3 · review by 12 Dec
Accepts falls without injury, frailty, age 18+, DT1 to DT4, 08:00 to 20:00
Does not accept suspected fracture, head injury on anticoagulants, needs IV therapy
Advisors rely on these. If they are out of date, advisors see a flag on your service.
[btn] Still right
[btn] Change
3 Confirm: still right
[btn] [Back] 
Confirm
## Are these still right?
By confirming, you say the criteria are current and safe for advisors to rely on.
Review again in
[btn] 3 months
[btn] 6 months
[btn] 12 months
We log your confirmation, the date and your role.
[btn] I confirm
[btn] Back
4 Change the criteria
[btn] [Back] 
Edit criteria
Needs you acceptRequired
[btn] Fall, no injury
[btn] Frailty
[btn] Wound care
[btn] IV therapy
[btn] Palliative
[btn] Dementia
Youngest ageChanged[input text value='16' placeholder=''][Youngest age] 
Needs you do not acceptRequired
[btn] Suspected fracture
[btn] Head injury on anticoagulants
[btn] Needs IV therapy
[btn] Infection isolation
[btn] No exclusions
Postcode districtsRequired
[btn] DT1
[btn] DT2
[btn] DT3
[btn] DT4
[btn] Preview
[btn] Cancel
5 Preview
[btn] [Back] 
Preview
What advisors will see
UCR West
Accepts: falls without injury, frailty, age 16+
Does not accept: suspected fracture, head injury on anticoagulants
What changed
Youngest age 18 to 16
[btn] Continue
[btn] Back
6 Send for approval
[btn] [Back] 
Send
## Send for second approval
Why are you changing this?Required
Short. No patient information.[input text value='[Reason]' placeholder='']
Review again in
[btn] 3 months
[btn] 6 months
[btn] 12 months
A SPOA clinical lead approves it too. Until then, advisors still see version 3.
[btn] Send for approval
[btn] Back
7 Status
[btn] [Back] 
Version 4
## Waiting for approval
Sent
14:02, by you
Second approval
SPOA clinical lead
Live
Advisors see version 4
We will tell you by notification. If it is sent back, you will see the note.
[btn] Back to my services
8 Overdue
[btn] [Back] 
Overdue
Review overdue
## Criteria not reviewed since 12 Sep
Advisors see a flag on UCR West: “criteria not reviewed”.
Not your service any more? Ask the shift lead to change the owner.
[btn] Review now
[btn] Ask to change the owner
9 Version history
[btn] [Back] 
History
Version 4Waiting
Version 312 Sep · [Role]
Version 24 Jun · [Role]
Version 1At registration
Every version stays in the audit record.
[btn] Start a new draft from version 3
10 Clinical lead approves
[btn] [Back] 
Approve change
Second approval · UCR West
What changed
Youngest age: 18 to 16
Reason from [Role]: [reason]
Safe for advisors to rely on?
[btn] Yes, approve
[btn] Send back
Note (if sending back)Optional[input text value='' placeholder='']
[btn] Submit my decision
[btn] Cancel

## Artboard: OnboardReporter1

Service reporter set-up: steps 1 to 6
1 Invitation text
[btn] [Back] 
D
DIUCS capacity
07700 900123
Today 09:00
DIUCS: You are invited to report capacity for UCR West. Set up takes about 3 minutes: diucs.example/i/Qx82 Valid for 48 hrs.
Message[input text value='' placeholder='Text message']
[btn] [Send] 
2 Welcome
[btn] [Back] 
Set up
## Set up capacity reporting for UCR West
1
Check your number
30 seconds
2
Choose how we contact you
1 minute
3
Add to home screen
1 minute, app only
4
Allow notifications
App only
5
Create a PIN
30 seconds
You can stop and come back to the link within 48 hours.
[btn] Start
3 Check your number
[btn] [Back] 
Step 1 of 5
## Check your mobile number
We will send a 6-digit code to this number.
07xxx xxx456
Not your number? Ask the SPOA shift lead to send a new invitation.
[btn] Send code
4 Enter the code
[btn] [Back] 
Step 1 of 5
## Enter your code
We sent a code to 07xxx xxx456.
6-digit code[input text value='482' placeholder='']
4
8
2
Send a new code in 0:42
The code works for 10 minutes. After 5 wrong tries you must ask for a new code.
[btn] Check code
5 Choose how
[btn] [Back] 
Step 2 of 5
## How should we contact you?
[btn] App notificationRecommended. A notification opens the app. Needs adding to your home screen.
[btn] Text messageA text with a link. Works on any phone.
[btn] EmailAn email with a link.
You can change this later in Settings.
[btn] Continue
6 Add to home screen
[btn] [Back] 
Step 3 of 5
## Add DIUCS to your home screen
[btn] iPhone
[btn] Android
1. Tap Share
The square with an arrow, at the bottom of the screen
2. Tap Add to Home Screen
Scroll down the list if you cannot see it
3. Tap Add
The DIUCS icon appears on your home screen
4. Open DIUCS from the home screen
Carry on there. Notifications only work from the home screen.
iPhone needs iOS 16.4 or later.
[btn] I have added it
[btn] I cannot do this. Use text instead

## Artboard: OnboardReporter2

Service reporter set-up: steps 7 to 12
7 Open from home screen
D
DIUCS capacity
Welcome. Your set-up continues here.
[btn] Continue
8 Turn on notifications
[btn] [Back] 
Step 4 of 5
## Turn on notifications
What we send
Capacity requests and booking requests for UCR West.
What we never send
Patient names or details.
You choose
Turn them off any time in Settings.
When you allow, we record the date and this phone.
[btn] Allow notifications
[btn] Not now. Use text instead
9 Phone asks permission
## Turn on notifications
“diucs.example” would like to send you notifications
[btn] Allow
[btn] Don’t allow
10 Create a PIN
[btn] [Back] 
Step 5 of 5
## Create a 6-digit PIN
You enter it each time you open the app. We text you a code again every 30 days.
[3 of 6 digits entered] 
[btn] [1] 1
[btn] [2] 2
[btn] [3] 3
[btn] [4] 4
[btn] [5] 5
[btn] [6] 6
[btn] [7] 7
[btn] [8] 8
[btn] [9] 9
[btn] [0] 0
[btn] [Delete] ⌫
11 Confirm the PIN
[btn] [Back] 
Step 5 of 5
## Enter it again
Type the same PIN to confirm.
[6 of 6 digits entered] 
[btn] [1] 1
[btn] [2] 2
[btn] [3] 3
[btn] [4] 4
[btn] [5] 5
[btn] [6] 6
[btn] [7] 7
[btn] [8] 8
[btn] [9] 9
[btn] [0] 0
[btn] [Delete] ⌫
12 All set
[btn] [Back] 
All set
## You are set up
ServiceUCR West
Contact byApp notification
Phone07xxx xxx456
Next update due10:00
Text code needed againIn 30 days
[btn] Send me a test notification
[btn] Go to the app

## Artboard: ReporterApp1

Service reporter app: daily use
1 Notification
Friday 23 October
10:00
DDIUCS capacitynow
UCR West: confirm or update
We have 3 referrals recorded. Reply by 10:30.
2 Enter your PIN
[btn] [Back] 
DIUCS capacity
## Enter your PIN
[2 of 6 digits entered] 
[btn] [1] 1
[btn] [2] 2
[btn] [3] 3
[btn] [4] 4
[btn] [5] 5
[btn] [6] 6
[btn] [7] 7
[btn] [8] 8
[btn] [9] 9
[btn] [0] 0
[btn] [Delete] ⌫Forgot your PIN?
3 Respond
DIUCS capacity
UCR West
Capacity update
We have 3 referrals in the next 2 hours, as of 08:15. Still right?
[btn] Yes, still 3
Or send a new number
[btn] [Decrease by one] 
Referrals in the next 2 hours[input text value='4' placeholder='']
[btn] [Increase by one] 
referrals · usual range 0 to 8
[btn] Send new number
[btn] We are closed to referrals
4 Confirmation
DIUCS capacity
UCR West
## Thank you
UCR West: 4 referrals recorded at 10:12.
Next update due 12:00
Today
10:124 referrals
08:153 referrals
[btn] Change it
5 Booking request notification
Friday 23 October
14:16
DDIUCS capacitynow
Booking request 4821: UCR West
Reply by 14:26. Not booked until you confirm.
6 Decide
DIUCS capacity
UCR West
Booking request 4821
Age band 80+
Need Fall and frailty
Wanted Within 2 hrs
Referral details follow in SystmOne.
[btn] Confirm booking
Or decline. Why? (optional)
[btn] Full
[btn] Outside criteria
[btn] Staffing
[btn] Other
[btn] Decline
Reply by 14:26.
7 Booked
DIUCS capacity
UCR West
## Booked
Reference 4821, UCR West. Confirmed 14:19. The advisor has been told.
Referral details follow in SystmOne.
Something changed? Phone the SPOA on [SPOA phone number].

## Artboard: ReporterApp2

Service reporter app: recovery and settings
1 Every 30 days: check it is you
[btn] [Back] 
Check it is you
## Check it is you
It has been 30 days. We will text a code to 07xxx xxx456.
You do not need to do this again for another 30 days.
[btn] Send code
2 PIN locked
[btn] [Back] 
PIN locked
## Your PIN is locked
That was 5 wrong tries. Get a code by text to set a new PIN.
Nothing was sent or changed.
[btn] Text me a code
[btn] Use text or email instead
3 Settings
[btn] [Back] 
Settings
Contact me byApp notification
NotificationsOn
Phone07xxx xxx456
Cover numberNot set
Text code needed againIn 21 days
[btn] Change how we contact me
[btn] Add a cover number
[btn] Sign out of this phone
4 Notifications are blocked
[btn] [Back] 
Notifications off
## Notifications are off
We cannot alert you. Turn them on in your phone settings, or switch to text.
1
Open your phone Settings
2
Find DIUCS capacity
3
Turn Notifications on
[btn] Use text instead
[btn] I have turned them on

## Artboard: MultiServicePhone

One phone, several services
1 One notification
Friday 23 October
10:00
DDIUCS capacitynow
2 services need an update
UCR West and UCR East. Reply by 10:30.
2 Update both
DIUCS capacity
2 services
Update by 10:30
[btn] Both still right (3 and 1)
UCR West
We have 3 referrals. Still right?
[btn] Still right
[btn] Change
UCR East
We have 1 referral. Still right?
[btn] Still right
[btn] Change
Each service is confirmed separately in the record.
3 Change one
DIUCS capacity
Updating UCR East
UCR East · 1 of 2
UCR East
Or send a new number
[btn] [Decrease by one] 
Referrals in the next 2 hours[input text value='2' placeholder='']
[btn] [Increase by one] 
referrals · usual range 0 to 8
[btn] Send new number
[btn] Back to both
4 Confirmation
DIUCS capacity
2 services
## Thank you
UCR West3 referrals · 10:12
UCR East2 referrals · 10:13
Next update due 12:00
5 Text for two services
[btn] [Back] 
D
DIUCS capacity
07700 900123
Today 10:00
DIUCS: 2 services need an update by 10:30. A) UCR West 3. B) UCR East 1. Reply Y if both right, or A 4, or B 2.
B 2
10:13
Thanks. B) UCR East updated to 2. A) UCR West still needs a reply: Y A, or A and a number.
Y A
10:14
Thanks. A) UCR West 3 confirmed. Next prompt 12:00.
Message[input text value='' placeholder='Text message']
[btn] [Send] 
6 My services
DIUCS capacity
3 services
My services
UCR West
Confirmed 10:12
Next due 12:00
UCR East
Due now
By 10:30
Virtual ward
Paused
Until 08:00 tomorrow
To add a service, ask the SPOA shift lead. New services are added by invitation and checked.
[btn] Add a service
7 Booking request
DIUCS capacity
UCR East only
This request is for
UCR East
Booking request 4821
Age band 80+
Need Fall and frailty
Wanted Within 2 hrs
Reply by 14:26. Not booked until you confirm.
[btn] Confirm booking for UCR East
[btn] Decline
8 A service was added
DIUCS capacity
Add a service
## UCR North has been added
The SPOA shift lead added UCR North to your account. Do you look after it?
We check this with the service before it goes live. Your other services are not affected.
[btn] Yes, I look after UCR North
[btn] No, this is not me
9 Hand over one service
DIUCS capacity
Cover
## Cover for UCR East
Choose who takes UCR East while you are away. Your other services stay with you.
Cover mobile numberRequired[input text value='[07xxx xxxxxx]' placeholder='']
Until
[btn] Tonight
[btn] This week
[btn] A date
We text them a code to check the number. The SPOA shift lead is told.
[btn] Hand over UCR East

## Artboard: MultiServiceAdmin

Shift lead: phones and services
1 Phones and services
diucs.example/admin
## Phones and services
Phones and the services they report for
Phone | Role | Services | Channel | Last seen | Flag | 
…456 | Duty manager | UCR West, UCR East | App | 10:12 | | 
…021 | Virtual ward coordinator | 3 pathways | App | 09:40 | | 
…777 | Ward manager | Ward A, B, C, D | Text | 08:15 | Holds 4 services | 
More than 3 services on one phone slows replies.
[btn] Move a service
[btn] Add a service to a phone
2 Move a service
diucs.example/admin
## Move a service to another phone
ServiceRequired[input text value='UCR East' placeholder='']
From…456, Duty manager
To mobile numberRequired[input text value='[07xxx xxxxxx]' placeholder='']
How long?
[btn] Until I change it
[btn] Cover until a date
1
We text the new phone a code
2
You phone the service on the number from the register
3
The service goes to the new phone
[btn] Start the move
[btn] Cancel
The old phone keeps its other services.

## Artboard: SafetyConcern

Safety concern, problem report and session sharing
1 Help
[btn] [Back] 
Help
## Help
[btn] Report a safety concern
[btn] Something is wrong with the tool
[btn] Share my session with support
[btn] Read the one-page guide
Help is one tap away on every screen.
2 Report a safety concern
[btn] [Back] 
Safety concern
## Report a safety concern
What is it about?Required
Categories are to be agreed with the clinical safety officer.
[btn] Wrong service shown
[btn] Out-of-date criteria
[btn] Wrong status on the board
[btn] A message went to the wrong place
[btn] Something else
Case or booking referenceOptional
If you have one[input text value='[Reference]' placeholder='']
What happened?Required
Up to 280 characters. No patient names or details.[input text value='' placeholder='']
If someone is at risk now, phone the SPOA or follow local procedure first.
[btn] Send to the clinical safety officer
[btn] Cancel
3 Sent
[btn] [Back] 
Sent
## Concern SC-0192 sent
A clinical safety officer will review it. You will be told when it has been looked at.
If someone is at risk now, phone [SPOA phone number].
[btn] Done
4 Problem with the tool
[btn] [Back] 
Report a problem
## What is wrong?
Choose oneRequired
[btn] A screen is slow
[btn] A button does not work
[btn] A figure looks wrong
[btn] Something else
Tell us moreOptional
Up to 280 characters. No patient names or details.[input text value='' placeholder='']
Help us find itOptional
Support can see the pages and buttons you used. Not what you typed.
[btn] Share my session with support
[btn] Send report
[btn] Cancel
5 Share my session
[btn] [Back] 
Share my session
## Your support code
K7R4-92QX
Sample code. Valid for [period].
Support can see the pages you used, the buttons you pressed and any errors. They cannot see what you typed or any patient information.
Who has opened your session
14:02 by [Support role]
[btn] Copy code
[btn] Stop sharing now

## Artboard: SuspendLeaver

Suspend, remove, lost phone, flagged reports
1 Lead: suspend
[btn] [Back] 
Suspend UCR East
## Suspend UCR East
What happens at once
The board shows Not updated, phone to confirm.
The service leaves the options.
Prompts stop.
Open requests expire.
Why?Required
[btn] Suspected false reports
[btn] Closed unexpectedly
[btn] Contact cannot be reached
[btn] Other
[btn] Suspend service
[btn] Cancel
2 Lead: suspended
[btn] [Back] 
UCR East
Suspended
## UCR East is suspended
Since 14:20. 2 open requests expired.
The service was told by text. Resuming needs a call-back.
[btn] Phone the service
[btn] Resume service
3 Lead: resume
[btn] [Back] 
Resume UCR East
## Before you resume
Both are neededRequired
[btn] I phoned the service on the register number
[btn] The reason is resolved
Resuming is logged with who and when.
[btn] Resume service
[btn] Cancel
4 Lead: remove a person
[btn] [Back] 
Remove a person
## Remove a person
PersonRequired[input text value='[Role or phone ending]' placeholder='']
Why?Required
[btn] Left the service
[btn] Changed role
[btn] Lost phone
[btn] Other
What happens
The phone is signed out everywhere.
Notifications stop.
Prompts go to the cover number, or to you.
Past reports stay in the record.
[btn] Remove access
[btn] Cancel
5 Reporter: lost phone
[btn] [Back] 
Lost your phone?
## Lost your phone?
Use your new phone. We text a code to the number we have for you.
Mobile numberRequired[input text value='[07xxx xxxxxx]' placeholder='']
Your old phone is signed out as soon as you verify. The SPOA shift lead phones your service before your new phone goes live.
[btn] Send code
[btn] Back
6 Reporter: waiting
[btn] [Back] 
Waiting
## Waiting for a call-back
The shift lead will phone your service on the number on the register. Until then, prompts go to your cover number or the SPOA.
[btn] Phone the shift lead
7 Lead: reports to check
[btn] [Back] 
Reports to check
[btn] To check (2)
[btn] Checked
UCR East reported 40, twice
Usual range 0 to 8. Sent 14:10 and 14:12 by text.
[btn] Phone to confirm
[btn] Accept the figure
[btn] Suspend service
Ward A: 3 reports in 4 minutes
All Y, then 9, then 2.
[btn] Phone to confirm
[btn] Mark as checked
Flagged by rules: out-of-range twice, many changes in a short time, or a figure that differs from what advisors recorded by phone.
8 Sign out everywhere
[btn] [Back] 
Sign out
## Sign out of every phone?
Use this if a phone is lost, shared or stolen. You will sign in again with a text code and your PIN.
This phone and 1 other will be signed out.
[btn] Sign out of all phones
[btn] Cancel

## Artboard: ExecApp1

COO and ICB app: home, service, week, alerts
1 Home: system now
[btn] [Back] 
Dorset system
Watch
3 of 9 services limited or worse
Accepting
4
Limited
2
Not accepting
1
Over capacity
1
Not updated
1
Needs attention (3)
Hospital at home
Over capacity +4 since 13:10
SDEC · Site 2
Not accepting since 12:50
Virtual ward · frailty
Not updated for 4 hrs 10 minSample data
[btn] See all services
2 Service detail
[btn] [Back] 
Hospital at home
Over capacityUpdated 11 min ago
+4
over established capacity
16 of 12 virtual beds
Today
[Over capacity since 13:10. Peak of 4 over at 14:00.] 
Over capacity since 13:10. Peak +4 at 14:00.
Reported byText, duty coordinator
AlertAcknowledged by [Role] 13:40
Escalation in placeYes
[btn] Call the duty coordinator
[btn] Back to alerts
3 This week
[btn] [Back] 
This week
17 to 23 OctSample data
640
referrals
18%
best fit not available
92%
capacity updates on time
4 min
median time to a confirmed booking
Time back (estimate)
412 updates by text, app or email. Each replaces about one phone call of [x] minutes.
Estimate until we measure the baseline. Counts under 10 are hidden. Outcomes are not shown yet.
[btn] Send me this each Monday
4 Alerts
[btn] [Back] 
Alerts
[btn] Open (2)
[btn] Acknowledged
[btn] Closed
Hospital at home over capacity
+4 since 13:10
New · alerted 14:12
[btn] Acknowledge
[btn] Open
SDEC · Site 2 not accepting
Since 12:50
Acknowledged by you 13:05
Acknowledging tells others it is being handled. It does not change the board.

## Artboard: ExecApp2

COO and ICB app: set-up, alerts and escalation
1 Invitation text
[btn] [Back] 
D
DIUCS capacity
07700 900123
Today 08:00
DIUCS: You are invited to see Dorset urgent care capacity on your phone. Set up takes about 3 minutes: diucs.example/i/Ab41 Valid for 48 hrs.
Message[input text value='' placeholder='Text message']
[btn] [Send] 
2 Welcome
[btn] [Back] 
Welcome
## The whole system in your pocket
See what is open, what is under pressure, and get an alert only when it matters.
Fewer status calls and catch-up meetings
Pressure seen as it builds, not at the next meeting
No patient information, ever
[btn] Choose my alerts
3 Choose your alerts
[btn] [Back] 
Your alerts
A service closes unexpectedly
Not planned out-of-hours closures
[btn] [A service closes unexpectedly] On
A service goes over capacity
When it moves past its established level
[btn] [A service goes over capacity] On
A service has not updated
After 2 hrs. Choose 2 or 4 hrs.
[btn] [A service has not updated] On
System pressure rises
When 5 or more services are limited or worse
[btn] [System pressure rises] On
Daily summary
07:30, by notification
[btn] [Daily summary] On
Weekly summary
Mondays, by email
[btn] [Weekly summary] Off
Alerts never include patient information. You can change these at any time.
[btn] Save my alerts
4 Escalation alert
Friday 23 October
14:12
DDIUCS capacitynow
Hospital at home: over capacity
+4 since 13:10. Tap to acknowledge.
5 Acknowledge
[btn] [Back] 
Alert
Over capacity
## Hospital at home
+4 over established capacity since 13:10. Last updated 11 min ago.
Alerted 14:12.
If nobody acknowledges within 15 min, [Deputy role] is alerted.
Acknowledging tells others it is being handled.
[btn] Acknowledge
[btn] Call the duty coordinator
[btn] Snooze for 1 hour
6 Quiet hours and escalation
[btn] [Back] 
Escalation
Quiet hours
[btn] 22:00 to 06:00
[btn] None
During quiet hours, alert me about
[btn] Critical only
[btn] Everything
If I do not acknowledge within
[btn] 10 min
[btn] 15 min
[btn] 30 min
Then alertRequired[input text value='[Deputy role or name]' placeholder='']
The ladder: you, then your deputy, then the SPOA shift lead by phone.
[btn] Save

## Artboard: PlanningView

Planning view: right-sizing
DIUCS capacity · Planning
Managers and ICB · sign in with Trust account
## Right-sizing: where capacity ran outSample data
Period
[btn] Last 30 days
[btn] Last 90 days
[btn] Last 12 months
Need group
[btn] All
[btn] Falls and frailty
[btn] IV therapy
[btn] Palliative
Cohort: age 65+, falls and frailty, within 2 hrs, ambulance crew or care home referrers. Groups under 10 are hidden.
640
referrals
Last 90 days, falls and frailty
112
best fit unavailable
18% of referrals. Full, closed or not updated.
62
went to another suitable service
The rest: fewer than 10 per destination, or no destination recorded
## Where they went when the best fit was full
Counts under 10 are not shown, to protect small groups.
Referrals by best fit service and where the patient went instead
Best fit, and its state | Went to | Referrals | Share | 
Hospital at home · full | UCR West | 18 | 
 | 
Hospital at home · full | Community hospital · Ward B | 11 | 
 | 
Hospital at home · full | Emergency department | fewer than 10 | 
 | 
UCR East · closed | SDEC · Site 1 | 22 | 
 | 
UCR East · closed | UCR West | 15 | 
 | 
UCR East · closed | Emergency department | 12 | 
 | 
Ward A · full | Ward B | fewer than 10 | 
 | 
[btn] Export table (CSV)
[btn] Show cohort definition
## When the best fit was unavailable
Referrals by day and time of day
Mon
Tue
Wed
Thu
Fri
Sat
Sun
00 to 06
1
0
1
1
2
2
3
06 to 12
3
2
3
3
4
5
4
12 to 18
6
5
6
9
7
6
5
18 to 24
4
3
4
5
6
7
5
Busiest: Thursday 12:00 to 18:00 (9)
## Declined despite showing capacity
By service, last 90 days
Community hospital · Ward A14
SDEC · Site 111
UCR East10
For a conversation with each service. Not a league table and not used to assess advisors.
## How to read this
These are referral and acceptance counts from the SPOA decision log. They do not show what happened to patients afterwards. Outcomes need linked data and come in phase 2.
Who acts on these findings: [owner to be agreed].

## Artboard: MapWeb

Map: advisor on web
1 Map and list
diucs.example/case/4821/map
## Options near DT4 8XX
Same services as the list. Sorted by travel time. Not ranked.
[btn] Map
[btn] List
[Patient area, postcode centre] 
Patient area
[btn] [UCR West (visits)] UCR West (visits)
[btn] [Hospital at home (visits)] Hospital at home (visits)
[btn] [Ward B] Ward B
Map: licensed tiles. Patient shown at postcode centre.
Dashed areas are where a visiting service can attend. The dotted line is the route to the selected site.
Community hospital · Ward B
Accepting
Free 5 beds
Patient to ward by road 35 to 50 min
Updated 2 hrs 10 min ago
[btn] Request booking
[btn] Criteria
[btn] Travel details
2 Travel details
diucs.example/case/4821/map
## How the travel time is worked out
Leg | Range | How | Source | 
Patient to Ward B, by road | 35 to 50 min | Typical weekday afternoon. The spread is from traffic. | Routing data, updated [date] | 
Visiting services | Included in their response time | UCR West: about 1 hr 20 from request, not a separate travel figure | Service profile | 
A range, not a promise.
Roads, weather and the time of day change it. The patient is placed at the postcode centre, so the range is for the area, not the door.
[btn] Report a wrong estimate
[btn] Back to the map
3 Postcode not found
diucs.example/case/4821/map
## We could not find that postcode
Check it with the caller, or choose the district.
PostcodeOptional[input text value='DT4 8X' placeholder='']
[btn] Search again
Or choose the districtOptional
Options will use the district, with a wider travel range.
[btn] DT1
[btn] DT2
[btn] DT3
[btn] DT4
[btn] DT5
[btn] Other
What instead
[btn] Ask a clinical advisor
[btn] Phone a service you know has space
4 Outside Dorset
diucs.example/case/4821/map
## No service covers this area
DT4 8XX is outside the areas the services here cover. Do not leave the caller without a next step.
[btn] Ask a clinical advisor
[btn] Other routes under local protocol
[btn] Change the postcode
Out-of-area referrals are recorded as an outcome so the coverage can be reviewed.

## Artboard: MapPhone

Map: advisor on phone
1 Map
Options near DT4 8XX
3 services · not ranked
[btn] Map
[btn] List
[Patient area, postcode centre] 
Patient area
[btn] [UCR West] UCR West
[btn] [Hospital at home] Hospital at home
[btn] [Ward B] Ward B
Map: licensed tiles. Patient shown at postcode centre.
Ward B
Accepting
35 to 50 min by road · 5 beds free
2 Pin detail
[btn] [Back] 
Ward B
Accepting
## Community hospital · Ward B
Free5 beds
By road35 to 50 min
Data age2 hrs 10 min
CriteriaVersion 2
A range, not a promise. The patient is placed at the postcode centre.
[btn] Request booking
[btn] Criteria
[btn] Travel details
3 List (same options)
[btn] [Back] 
Options
[btn] Map
[btn] List
UCR West
Accepting
Visits, about 1 hr 20 · 9 min old
Hospital at home
Over capacity
Review within about 3 hrs · 14 min old
Community hospital · Ward B
Accepting
35 to 50 min by road · 2 hrs 10 min old
The list is always available and has everything the map shows.
4 Postcode not found
[btn] [Back] 
Postcode
## We could not find that postcode
PostcodeOptional[input text value='DT4 8X' placeholder='']
Or choose the districtOptional
[btn] DT1
[btn] DT2
[btn] DT3
[btn] DT4
[btn] Other
[btn] Ask a clinical advisor
[btn] Phone a service you know has space
[btn] Search again
[btn] Back

## Artboard: ConsoleA

Support and insight console: sessions and traces
1 Find a session
diucs.example/console
## Find a session
Opening one session needs a support code the person shared, or an approved ticket. Every open is logged and shown to the person.
Support codeOptional[input text value='[Support code]' placeholder='']
[btn] Open session
Or search
Session idOptional[input text value='' placeholder='']
Trace idOptional[input text value='' placeholder='']
Booking or case referenceOptional[input text value='' placeholder='']
RoleOptional
[btn] Reporter
[btn] Advisor
[btn] Clinical
[btn] Lead
[btn] Exec
ReleaseOptional
[btn] Latest
[btn] Previous
[btn] Last 24 hours
[btn] Last 7 days
[btn] Last 30 days
[btn] Search
Session | Role | Device | Release | Started | Events | Friction | Errors | | 
s-7f3a | Advisor | Desktop | 1.4.2 | 13:02 | 212 | 3 | 1 | 
[btn] Open | 
s-91c0 | Reporter | Phone | 1.4.2 | 13:40 | 38 | 0 | 0 | 
[btn] Open | 
Search shows aggregates and session ids only. Opening a timeline asks for a support code or a ticket approval.
2 Session timeline
diucs.example/console
## Session s-7f3a
Advisor · Desktop · release 1.4.2 · 01:10 long · code valid until 14:30
What stands out
Rage click on ADV-OPT-REQUEST-BTN while POST /api/bff/bookings took 2.4 s.
[btn] All
[btn] Errors
[btn] Friction
[btn] API
[btn] Navigation
00:00Page view/case/[ref]
00:08ClickADV-NEEDS-AGE-80PLUSdom
00:21InputADV-NEEDS-POSTCODEvalid
00:44ClickADV-OPT-REQUEST-BTNnetwork1.8 s
00:45FrictionADV-OPT-REQUEST-BTNimpatient click
00:46FrictionADV-OPT-REQUEST-BTNrage click, 3 in 1 s
00:47APIPOST /api/bff/bookings2012.4 s
[btn] View trace
01:10Page view/case/[ref]/options
[btn] Copy link to this moment
[btn] Close session
Events show element ids and outcomes. Field values and page text are never recorded.
3 Trace
diucs.example/console
## Trace for POST /api/bff/bookings
Total 2.4 s · 8 spans · success
Browser click ADV-OPT-REQUEST-BTN
fetch POST /api/bff/bookings
bff.bookings
fhir.create Task
usecase.RequestBooking
neo4j Q-TASK-BOOK-CREATE
neo4j Q-OUTBOX-ADD
servicebus.publish booking.events
Slowest
neo4j Q-TASK-BOOK-CREATE took 1.2 s. Budget for this query is 200 ms.
Span | Duration | Status | Attributes | 
neo4j Q-TASK-BOOK-CREATE | 1.2 s | OK | rows 1, mode write | 
servicebus.publish booking.events | 0.3 s | OK | message id [id] | 
[btn] Open the query in the matrix
[btn] Back to the session
4 Funnels
diucs.example/console
## Funnels
Sample data
FunnelOptional
[btn] Reporter set-up
[btn] Daily capacity loop
[btn] Booking, service side
[btn] Advisor call
[btn] Registration
[btn] Criteria review
[btn] COO and ICB adoption
[btn] Last 24 hours
[btn] Last 7 days
[btn] Last 30 days
Invitation delivered
100%
Link opened
82%
Code verified
71%
Channel chosen
69%
Home-screen guide viewed
51%
Notifications allowed
44%
PIN created
41%
First prompt answered
38%
Biggest drop
Link opened to Code verified: 11 points. Exit element: ONB-CODE-SEND-BTN. Median time between steps: 48 s.
Split | Conversion | 
Text link | 44% | 
Email link | 31% | 
App | 52% | 
[btn] Export CSV

## Artboard: ConsoleB

Support and insight console: insight
5 Navigation paths
diucs.example/console
## Navigation paths
Sample data
RoleOptional
[btn] Advisor
[btn] Reporter
[btn] Lead
[btn] Exec
[btn] Last 24 hours
[btn] Last 7 days
[btn] Last 30 days
Most common routes
Route | Sessions | Median time on page | 
/case/[ref] | 212 | 1 min 20 s | 
/case/[ref]/options | 198 | 48 s | 
/case/[ref]/finish | 176 | 35 s | 
U-turns: left within 5 s
From to back | Count | 
/case/[ref]/options to /case/[ref] | 18 | 
/lead to /lead/phones | 11 | 
Never used this week
ADV-SCORE-MANCHESTER-CHIP, EXEC-WEEKLY-EMAIL-BTN
6 Friction by element
diucs.example/console
## Friction by element
Elements over 5% are reviewed. Sample data.
DeviceOptional
[btn] All
[btn] Phone
[btn] Tablet
[btn] Desktop
[btn] Last 24 hours
[btn] Last 7 days
[btn] Last 30 days
Element | Kind | Events | Interactions | Rate | 
ADV-OPT-REQUEST-BTN | Impatient and rage click | 41 | 312 | 13% | 
REG-STEP3-PHONE-FIELD | Validation loop | 27 | 230 | 12% | 
ONB-CODE-SEND-BTN | Dead click | 19 | 260 | 7% | 
[btn] Show example sessions
Example sessions are anonymised timelines with no support code. They show the element and what happened next.
7 Performance
diucs.example/console
## Performance
Sample data
DeviceOptional
[btn] Phone
[btn] Tablet
[btn] Desktop
[btn] Last 24 hours
[btn] Last 7 days
[btn] Last 30 days
Measure | p75 | Budget | Status | 
Largest contentful paint | 2.1 s | 2.5 s | Within budget | 
Interaction to next paint | 240 ms | 200 ms | Over budget | 
Layout shift | 0.04 | 0.1 | Within budget | 
Slowest routes
Route | p95 | Budget | 
POST /api/bff/bookings | 2.4 s | 800 ms | 
GET /api/bff/board | 310 ms | 500 ms | 
Slowest Cypher queries
Query | p95 | Budget | 
Q-TASK-BOOK-CREATE | 1.2 s | 200 ms | 
Q-BOARD | 88 ms | 100 ms | 
Prompt to board
System time 4 s
Human time 8 min
8 Releases and pipeline
diucs.example/console
## Releases and pipeline
Sample data
CompareOptional
[btn] 1.4.2 with 1.4.1
[btn] 1.4.1 with 1.4.0
[btn] Compare releases
Measure | 1.4.1 | 1.4.2 | Change | 
INP p75, phone | 190 ms | 240 ms | Slower | 
Friction, request booking | 6% | 13% | Higher | 
Pipeline
Queue or topic | Active | Dead-lettered | Oldest | 
inbound.replies | 0 | 0 | 0 s | 
messages.outbound | 2 | 0 | 4 s | 
booking.events | 0 | 1 | n/a | 
A dead-lettered message raises an alert to engineering.

## Artboard: TourPhone1

Product tour: reporter
1 Welcome
[btn] [Back] 
Welcome
## Less chasing. Faster answers.
DIUCS capacity replaces phone calls, emails and whiteboards with one tap or one text.
Fewer phone calls
Fewer catch-up meetings
Capacity updated in seconds
[btn] Take the 1-minute tour
[btn] Skip for now
2 Pick your role
[btn] [Back] 
Your role
## What do you do?
[btn] I report capacity for a service
[btn] I take calls as an SPOA advisor
[btn] I am an SPOA shift lead
[btn] I am a clinical advisor
[btn] I am a COO or ICB lead
We show you what changes for your role.
[btn] Continue
3 What changes for you
[btn] [Back] 
Reporters
## Your day, before and after
Today
Phone calls from the SPOA asking for beds
Whiteboards and emails at set times
Chased when a report is late
With DIUCS
We ask. You tap. About 10 seconds.
The board is current, so fewer calls
Nobody chases you
A phone call today takes [x] minutes. We measure it in the pilot.
[btn] Next
4 How it works
[btn] [Back] 
How it works
## Three steps
1
We ask
A notification arrives at your usual time
2
You tap
Yes, still right. Or send a new number.
3
The SPOA sees it at once
The board updates. No call needed.
We never send or ask for patient information.
[btn] Next
5 Try it
[btn] [Back] 
Try it
Sample data
## Practice update
Practice. Nothing is sent.
We have 3 referrals in the next 2 hours. Still right?
[btn] Yes, still 3
[btn] Send a new number
[btn] Skip practice
6 Your first week
[btn] [Back] 
First week
## Your first week
Set up your phone
Reply to your first prompt
Add a cover number
Have a look at the live board
On Friday we show you what you saved: updates sent and phone calls avoided.
[btn] Go to my app

## Artboard: TourRoles

Product tour: what changes for each role
1 Call advisors
[btn] [Back] 
For call advisors
## For call advisors
Today
Phone several services to find space
Check whiteboards and emails that may be hours old
Key the same details into each referral
With DIUCS
See what is open, and how old each figure is
Request a booking by text and move on
Copy one summary into SystmOne
[btn] Try a practice call
[btn] Skip
2 Shift leads
[btn] [Back] 
For shift leads
## For shift leads
Today
Chase late reporters by phone
Keep a list of who covers whom
Hold catch-up meetings to find the picture
With DIUCS
See who has not reported and chase in one tap
Change a cover number in seconds
Everyone sees the same board, so fewer huddles
[btn] Invite a reporter
[btn] Skip
3 Clinical advisors
[btn] [Back] 
For clinical advisors
## For clinical advisors
Today
Interrupted by calls with no case ready
Asked the same questions again
With DIUCS
Requests arrive with the case and what the advisor saw
Advise on one screen and it is logged
[btn] Go on duty
[btn] Skip
4 COO and ICB
[btn] [Back] 
For COOs and ICB leads
## For COOs and ICB leads
Today
Ask for updates by phone and in meetings
Hear about pressure late
Cannot see unused capacity
With DIUCS
The system picture in your pocket
Alerts only for what you choose
A weekly summary replaces a meeting
[btn] Choose my alerts
[btn] Skip

## Artboard: TrainingPhone

Training and help
1 Training library
[btn] [Back] 
Learn
## 2-minute lessons
[btn] Reporter
[btn] Advisor
[btn] Shift lead
Reply to a prompt
2 min · done
Correct a figure
2 min
Cover when you are away
2 min
If notifications stop
2 min
[btn] Start the next lesson
2 A lesson
[btn] [Back] 
Correct a figure
## Correct a figure
1
Open the notification or the app
Enter your PIN
2
Send the right number
The new figure replaces the old one
3
Check the confirmation
It shows the time recorded
Corrections are fine. The board shows the latest figure and its time.
[btn] Try it in practice mode
[btn] Mark as done
3 Practice mode
[btn] [Back] 
Practice
Sample data
Practice. Nothing is sent.
We have 3 referrals in the next 2 hours. Still right?
[btn] Yes, still 3
[btn] Send a new number
[btn] Leave practice
4 Help in the moment
[btn] [Back] 
Help
## Need a hand?
[btn] Read the one-page guide
[btn] Ask your champion, [Name]
[btn] Phone the SPOA shift lead
[btn] Report a problem
Help is one tap away on every screen.
5 Your time back
[btn] [Back] 
This week
## This week
14
updates sent. About 14 phone calls avoided.
Estimate: each update replaces about one call. We will check this in the pilot.
The SPOA now sees your figure within seconds, so fewer calls come to your ward.
[btn] Share with my team

## Artboard: ValueCase

Selling the value
Selling the value
Fewer calls and meetings. Faster answers.
## What we promise, and how we prove it
## Services
One tap or one text, about 10 seconds
Fewer phone calls to the ward
Nobody chases you
## SPOA advisors and leads
See what is open and how old it is
Request by text and move on
Chasing late reporters is automatic
## Clinical advisors
Requests arrive with the case ready
Advice on one screen, logged
## COOs and ICB
System picture on your phone
Alerts only for what you choose
A weekly summary replaces a meeting
## What we measure
What we measure to show the value
Measure | Baseline (before) | From the tool (after) | Target | 
Phone calls to services per shift (SPOA) | Count on a sample of shifts, 2 weeks before go-live | Calls logged by reason: confirm capacity, confirm booking | [to agree] | 
Time from request to a confirmed place | Stopwatch on a sample of calls | Request sent to CONFIRMED, in minutes | [to agree] | 
Age of the capacity figure at the moment of a decision | Unknown today | Saved with every decision | [to agree] | 
Capacity updates on time | Not measured today | Updates received by the due time, per service | [to agree] | 
Meetings and huddles about capacity per week | Ask leads, check calendars | Same count after go-live, from calendars | [to agree] | 
Referrals declined despite showing capacity | Not measured today | Logged by service and hour | [to agree] | 
## Rules for claiming savings
No saving is claimed before the baseline is measured. Every estimate is labelled as an estimate and shows its sum. Show a range, not one number. The first week summary for each person reports real counts, such as updates sent, and says how the avoided-call figure is worked out.
## Launch kit
A one-minute product tour by role. Two-minute lessons with a practice mode. One champion per service and per shift. A one-page quick guide. A Friday summary of what each person saved.
