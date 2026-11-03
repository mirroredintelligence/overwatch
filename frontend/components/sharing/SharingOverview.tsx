'use client';

import { useState } from 'react';
import { Disclose } from '@/components/admin/Disclose';
import { AllowlistFields, canListFields } from '@/components/scope/AllowlistFields';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { Loading, SkeletonRows } from '@/components/ui/Skeleton';
import { StatusTag, type StatusTagVariant } from '@/components/ui/StatusTag';
import { post, queryFor, SHARING_BASE, useAdminRead, useNotice, type SharingPage, type SharingPageNetwork } from '@/lib/networkAdmin/browser';
import { NEVER_SHARED } from '@/lib/networkAdmin/fieldLabels';
import { arrivalWord, cardFor, cardWord, windowWord, type Card as KindCard, type CardState } from '@/lib/networkAdmin/sharing';
import { SCOPES, type Allowlist, type Scope } from '@/lib/networkAdmin/views';
import { dateText, SCOPE_WORD } from '@/lib/networkAdmin/words';
import styles from './Sharing.module.css';

// Sharing with the network, for the member organisation's administrator (TEN-081, design N2: SharingOverview,
// SharingFields, SharingEnd, SharingLeave, SharingAgreement, SharingHistory; board A6, right half). Sharing is read only.
// Each kind is a row that says its state in a tag and opens, on request, to what it shares and the actions that fit.
// One row is open at a time. A grant takes two approvals, the organisation's and the network owner's, from two different
// people. No patient information is ever shared, and no screen here holds a tenant's id, a handle or a person's reference.

export const INTRO = 'You share only what you agree to, and you can end it at any time. Each kind of sharing needs two approvals: one from you and one from the network owner.';

// The kinds as the board names them. The back end's own word for the directory is "Directory"; the screen says "Service directory".
const LABEL: Readonly<Record<Scope, string>> = { capacity: 'Capacity', directory: 'Service directory', criteria: 'Criteria' };
const DESCRIPTION: Readonly<Record<Scope, string>> = {
  capacity: 'How many places each service has now',
  directory: 'Which services you run and where',
  criteria: 'Which patients each service takes',
};
const WORD = (scope: Scope) => LABEL[scope].toLowerCase();

export function SharingOverview() {
  const { state, reload } = useAdminRead<SharingPage>(SHARING_BASE);
  const { notice, say } = useNotice();
  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Sharing with the network</h1>
      <p className={styles.text}>{INTRO}</p>
      <p className={styles.muted}>{NEVER_SHARED}</p>
      {state.status === 'loading' ? (
        <Loading label="Loading what your organisation shares.">
          <SkeletonRows count={3} />
        </Loading>
      ) : null}
      {state.status === 'failed' ? (
        <p role="alert" className={styles.problem}>
          We could not load what your organisation shares.
        </p>
      ) : null}
      {notice !== null ? (
        <p role={notice.ok ? 'status' : 'alert'} className={notice.ok ? styles.ok : styles.problem}>
          {notice.text}
        </p>
      ) : null}
      {state.status === 'ok' ? <Loaded page={state.data} reload={reload} say={say} /> : null}
    </main>
  );
}

type Say = (ok: boolean, text: string) => void;

function Loaded({ page, reload, say }: { page: SharingPage; reload: () => void; say: Say }) {
  return (
    <>
      <section aria-label="Your organisation code" className={`${styles.card} ${styles.codeCard}`}>
        <div className={styles.codeText}>
          <p className={styles.codeLabel}>Your organisation code</p>
          <p className={styles.codeValue}>{page.organisationCode}</p>
        </div>
        <CopyCode code={page.organisationCode} />
      </section>
      {page.networks.length === 0 ? <p className={styles.text}>Give this code to the network owner so they can invite you. You are not in a network yet.</p> : null}
      {page.networks.length === 0 ? (
        <Kinds network={null} allowlist={page.allowlist} reload={reload} say={say} />
      ) : (
        page.networks.map((network) => <NetworkSection key={network.id} network={network} allowlist={page.allowlist} reload={reload} say={say} />)
      )}
      <History networks={page.networks} />
    </>
  );
}

function CopyCode({ code }: { code: string }) {
  const [copied, setCopied] = useState<'idle' | 'copied' | 'failed'>('idle');

  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied('copied');
    } catch {
      setCopied('failed');
    }
  }

  return (
    <div className={styles.copy}>
      <Button variant="secondary" dataEl="SHARE-COPY-BTN" onClick={() => void copy()}>
        Copy
      </Button>
      {copied === 'copied' ? <span role="status" className={styles.ok}>Copied.</span> : null}
      {copied === 'failed' ? (
        <span role="alert" className={styles.problem}>
          The code could not be copied. Select it and copy it by hand.
        </span>
      ) : null}
    </div>
  );
}

function NetworkSection({ network, allowlist, reload, say }: { network: SharingPageNetwork; allowlist: Allowlist; reload: () => void; say: Say }) {
  const [leaving, setLeaving] = useState(false);
  const [accepting, setAccepting] = useState(false);
  const query = queryFor(network.id);
  const active = network.membershipStatus === 'active';
  const invited = network.membershipStatus === 'invited';
  const closed = network.membershipStatus === 'left' || network.membershipStatus === 'removed';

  async function accept() {
    if (accepting || network.agreementVersion === null) return;
    setAccepting(true);
    const result = await post(`${SHARING_BASE}/agreement`, query, { agreementVersion: network.agreementVersion });
    setAccepting(false);
    if (result.ok) {
      say(true, `Agreement version ${network.agreementVersion} accepted.`);
      reload();
    } else say(false, 'The agreement could not be accepted. Try again.');
  }

  return (
    <section className={styles.stack} aria-label={`Network ${network.name}`}>
      <h2 className={styles.networkName}>{network.name}</h2>
      {invited ? <p className={styles.text}>{`You have been invited to ${network.name}.`}</p> : null}
      {closed ? <p className={styles.text}>{`You left this network on ${dateText(network.leftAt)}.`}</p> : null}
      {network.agreementReference !== null && network.agreementVersion !== null ? <p className={styles.text}>{`Agreement ${network.agreementReference}, version ${network.agreementVersion}.`}</p> : null}
      {(invited || (active && network.agreementBehind)) && network.agreementVersion !== null ? (
        <div className={`${styles.card} ${styles.stack}`}>
          <p className={styles.text}>{`Agreement version ${network.agreementVersion} is available.`}</p>
          <div className={styles.actions}>
            <Button variant="primary" busy={accepting} dataEl="SHARE-AGREEMENT-ACCEPT-BTN" onClick={() => void accept()}>
              {`Accept version ${network.agreementVersion}`}
            </Button>
          </div>
        </div>
      ) : null}
      {invited ? null : <Kinds network={network} allowlist={allowlist} reload={reload} say={say} />}
      {active && !network.isOwner ? (
        <div className={styles.actions}>
          <Button variant="neutral" dataEl="SHARE-LEAVE-BTN" onClick={() => setLeaving(true)}>
            Leave network
          </Button>
        </div>
      ) : null}
      {leaving ? (
        <LeaveDialog
          network={network}
          query={query}
          onClose={() => setLeaving(false)}
          onLeft={() => {
            setLeaving(false);
            say(true, `You have left ${network.name}. What was shared stays in its history.`);
            reload();
          }}
        />
      ) : null}
    </section>
  );
}

// The three kinds, one row each. One row is open at a time; the parent holds which.
function Kinds({ network, allowlist, reload, say }: { network: SharingPageNetwork | null; allowlist: Allowlist; reload: () => void; say: Say }) {
  const [openKind, setOpenKind] = useState<Scope | null>(null);
  return (
    <div className={styles.stack}>
      {SCOPES.map((scope) => (
        <ScopeRow
          key={scope}
          scope={scope}
          network={network}
          allowlist={allowlist}
          open={openKind === scope}
          onToggle={() => setOpenKind(openKind === scope ? null : scope)}
          reload={reload}
          say={say}
        />
      ))}
    </div>
  );
}

function tagFor(state: CardState): { variant: StatusTagVariant; word: string } {
  switch (state.kind) {
    case 'sharing':
      return { variant: 'live', word: `Shared since ${dateText(state.since)}` };
    case 'scheduled':
      return { variant: 'due', word: cardWord(state) };
    case 'waiting-you':
    case 'waiting-owner':
      return { variant: 'waiting', word: cardWord(state) };
    case 'ended':
      return { variant: 'closed', word: cardWord(state) };
    case 'not-sharing':
      return { variant: 'todo', word: 'Not shared' };
  }
}

function ScopeRow({
  scope,
  network,
  allowlist,
  open,
  onToggle,
  reload,
  say,
}: {
  scope: Scope;
  network: SharingPageNetwork | null;
  allowlist: Allowlist;
  open: boolean;
  onToggle: () => void;
  reload: () => void;
  say: Say;
}) {
  const grants = network?.grants ?? [];
  const shared = network?.shared ?? [];
  const query = network === null ? '' : queryFor(network.id);
  const acting = network !== null && network.membershipStatus === 'active';
  const card = cardFor(scope, grants, shared);
  const fields = allowlist.scopes[scope];
  const listable = canListFields(scope, fields);
  const [busy, setBusy] = useState(false);
  const [dialog, setDialog] = useState<'decline' | 'end' | null>(null);
  const windowText = windowWord(card);
  const arrival = arrivalWord(card);
  const tag = tagFor(card.state);

  async function approve(grantId: string) {
    if (busy) return;
    setBusy(true);
    const result = await post<{ effective: boolean }>(`${SHARING_BASE}/grants/${encodeURIComponent(grantId)}/approve`, query);
    setBusy(false);
    if (result.ok) {
      say(true, result.data.effective ? `Approved. Sharing ${WORD(scope)} starts now.` : 'Your approval is recorded. Sharing starts when the network owner has approved too.');
      reload();
    } else if (result.status === 409) {
      say(false, 'That could not be done. If you gave the other approval yourself, another person must give this one.');
    } else say(false, 'That could not be done. Try again.');
  }

  async function propose() {
    if (busy) return;
    setBusy(true);
    const result = await post(`${SHARING_BASE}/grants`, query, { kind: scope });
    setBusy(false);
    if (result.ok) {
      say(true, 'Proposed. It now waits for your approval.');
      reload();
    } else if (result.status === 409) say(false, 'There is already an open proposal for this. Reload the page.');
    else say(false, 'That could not be done. Try again.');
  }

  return (
    <section aria-label={LABEL[scope]} data-el="SHARE-SCOPE-CARD" className={styles.kind}>
      <Disclose open={open} onToggle={onToggle} title={LABEL[scope]} hint={DESCRIPTION[scope]} aside={<StatusTag variant={tag.variant}>{tag.word}</StatusTag>}>
        <div className={styles.detail}>
          {windowText !== null ? <p className={styles.text}>{windowText}</p> : null}
          {card.inForceSince !== null ? <p className={styles.text}>{`Sharing is in force since ${dateText(card.inForceSince)} until this is decided.`}</p> : null}
          {arrival !== null ? <p className={styles.text}>{arrival}</p> : null}
          {card.state.kind === 'waiting-you' ? (
            <p className={styles.text}>A grant needs the approval of your organisation and of the network owner, from two different people.</p>
          ) : null}
          <AllowlistFields scope={scope} fields={fields} />
          {acting ? <Actions card={card} listable={listable} busy={busy} onApprove={(id) => void approve(id)} onPropose={() => void propose()} onDialog={setDialog} /> : null}
        </div>
      </Disclose>
      {dialog === 'decline' && card.waitingFor !== null ? (
        <GrantDialog
          kind="decline"
          scope={scope}
          grantId={card.waitingFor}
          query={query}
          onClose={() => setDialog(null)}
          onDone={() => {
            setDialog(null);
            say(true, 'Declined. Nothing is shared.');
            reload();
          }}
        />
      ) : null}
      {dialog === 'end' && card.endable !== null ? (
        <GrantDialog
          kind="end"
          scope={scope}
          grantId={card.endable}
          query={query}
          onClose={() => setDialog(null)}
          onDone={() => {
            setDialog(null);
            say(true, 'Sharing ended.');
            reload();
          }}
        />
      ) : null}
    </section>
  );
}

function Actions({
  card,
  listable,
  busy,
  onApprove,
  onPropose,
  onDialog,
}: {
  card: KindCard;
  listable: boolean;
  busy: boolean;
  onApprove: (grantId: string) => void;
  onPropose: () => void;
  onDialog: (dialog: 'decline' | 'end') => void;
}) {
  const word = WORD(card.scope);
  const buttons = [];
  if (card.waitingFor !== null) {
    // Nobody is asked to approve a list that is not the whole list.
    if (listable) {
      buttons.push(
        <Button key="approve" variant="primary" busy={busy} dataEl="SHARE-APPROVE-BTN" ariaLabel={`Approve sharing ${word}`} onClick={() => onApprove(card.waitingFor as string)}>
          Approve
        </Button>,
      );
    }
    buttons.push(
      <Button key="decline" variant="neutral" dataEl="SHARE-DECLINE-BTN" ariaLabel={`Decline sharing ${word}`} onClick={() => onDialog('decline')}>
        Decline
      </Button>,
    );
  } else if (card.endable !== null) {
    buttons.push(
      <Button key="end" variant="neutral" dataEl="SHARE-END-BTN" ariaLabel={`End sharing ${word}`} onClick={() => onDialog('end')}>
        End sharing
      </Button>,
    );
  } else if ((card.state.kind === 'not-sharing' || card.state.kind === 'ended') && listable) {
    buttons.push(
      <Button key="propose" variant="primary" busy={busy} dataEl="SHARE-PROPOSE-BTN" ariaLabel={`Propose sharing ${word}`} onClick={onPropose}>
        Propose sharing
      </Button>,
    );
  }
  return buttons.length === 0 ? null : <div className={styles.actions}>{buttons}</div>;
}

function GrantDialog({
  kind,
  scope,
  grantId,
  query,
  onClose,
  onDone,
}: {
  kind: 'decline' | 'end';
  scope: Scope;
  grantId: string;
  query: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const text =
    kind === 'end'
      ? {
          title: `End sharing ${WORD(scope)}?`,
          body: "New data stops being shared straight away. What was already shared stays in the network history, marked with today's date.",
          button: 'End sharing',
          el: 'SHARE-END-CONFIRM-BTN',
          failed: 'Sharing could not be ended. Try again.',
        }
      : {
          title: `Decline sharing ${WORD(scope)}?`,
          body: 'Nothing is shared. You can propose sharing again at any time.',
          button: 'Decline',
          el: 'SHARE-DECLINE-CONFIRM-BTN',
          failed: 'That could not be done. Try again.',
        };

  async function go() {
    if (busy) return;
    setBusy(true);
    setProblem(null);
    const result = await post(`${SHARING_BASE}/grants/${encodeURIComponent(grantId)}/${kind}`, query);
    setBusy(false);
    if (result.ok) onDone();
    else setProblem(text.failed);
  }

  return (
    <Dialog title={text.title} onClose={onClose}>
      <p className={styles.text}>{text.body}</p>
      {problem !== null ? (
        <p role="alert" className={styles.problem}>
          {problem}
        </p>
      ) : null}
      <div className={styles.actions}>
        <Button variant="primary" busy={busy} dataEl={text.el} onClick={() => void go()}>
          {text.button}
        </Button>
        <Button variant="neutral" onClick={onClose} dataEl="SCREENS-BOARD-CANCEL-BTN">
          Cancel
        </Button>
      </div>
    </Dialog>
  );
}

function LeaveDialog({ network, query, onClose, onLeft }: { network: SharingPageNetwork; query: string; onClose: () => void; onLeft: () => void }) {
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function leave() {
    if (busy) return;
    setBusy(true);
    setProblem(null);
    const result = await post(`${SHARING_BASE}/leave`, query);
    setBusy(false);
    if (result.ok) onLeft();
    else setProblem('You could not leave. Try again.');
  }

  return (
    <Dialog title={`Leave ${network.name}?`} onClose={onClose}>
      <p className={styles.text}>All your sharing ends now. What was already shared stays in the history, marked with the date you left.</p>
      {problem !== null ? (
        <p role="alert" className={styles.problem}>
          {problem}
        </p>
      ) : null}
      <div className={styles.actions}>
        <Button variant="primary" busy={busy} dataEl="SHARE-LEAVE-CONFIRM-BTN" onClick={() => void leave()}>
          Leave network
        </Button>
        <Button variant="neutral" onClick={onClose} dataEl="SCREENS-BOARD-CANCEL-BTN">
          Cancel
        </Button>
      </div>
    </Dialog>
  );
}

function History({ networks }: { networks: SharingPageNetwork[] }) {
  const [open, setOpen] = useState(false);
  const lines: string[] = [];
  for (const network of networks) {
    for (const grant of network.grants) {
      const since = `${SCOPE_WORD[grant.scope]}: Shared with ${network.name} since ${dateText(grant.effectiveFrom)}`;
      if (grant.status === 'approved' && grant.effective) lines.push(since);
      else if (grant.status === 'ended' || grant.status === 'lapsed' || grant.status === 'superseded') lines.push(`${since}. Ended on ${dateText(grant.endedAt)}`);
    }
  }
  const count = lines.length === 0 ? 'No changes yet' : `${lines.length} ${lines.length === 1 ? 'change' : 'changes'}`;
  return (
    <section id="history" aria-label="History" className={styles.kind}>
      <Disclose open={open} onToggle={() => setOpen(!open)} title="History" aside={<span className={styles.count}>{count}</span>}>
        <div className={styles.detail}>
          {lines.length === 0 ? (
            <p className={styles.text}>Nothing here yet.</p>
          ) : (
            <ul className={styles.list}>
              {lines.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          )}
        </div>
      </Disclose>
    </section>
  );
}
