import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { CONSENTED, VIEW_DETAIL_ACTIVE, VIEW_DETAIL_PROVISIONING, VIEW_DETAIL_READY, VIEW_DETAIL_SUSPENDED } from '@/test/fixtures/operator';
import { OPERATOR_SAMPLE_CSRF, resetOperatorWrites, seenOperatorWrites } from '@/test/msw/handlers/operator';
import { server } from '@/test/msw/server';
import { TenantDetail } from './TenantDetail';

// One partner organisation's page (TEN-083) as a guided "Go live": a task list of five parts (each a link with its
// status in words and one line on where it stands) and only the selected part beside it, by default the first that is
// not completed. A completed part shows a short summary and a Change link. Its identifiers are under a closed
// "Technical details" disclosure; Go live only when everything is done. Every write is the operator's own, with its
// CSRF token and one idempotency key per submit, and is the same write as before. A step that was done and not
// recorded by the platform chain is said so, and is never offered again. No secret is ever shown.

beforeEach(() => resetOperatorWrites());

type Detail = typeof VIEW_DETAIL_READY;
const serveConsent = (body: unknown) => server.use(http.get('/api/bff/platform/tenants/:id/admin-consent', () => HttpResponse.json(body as Record<string, unknown>)));
function serve(detail: unknown) {
  server.use(http.get('/api/bff/platform/tenants/:id', () => HttpResponse.json(detail as Record<string, unknown>)));
}
const PHASES = ['Organisation and sign-in', 'Administrator approval', 'Teams and people', 'Reach and agreements', 'Go live'];
/** Opens the page, and (when a part is named) chooses it in the task list. */
async function open(detail: unknown = VIEW_DETAIL_PROVISIONING, consent?: unknown, phase?: string) {
  serve(detail);
  if (consent !== undefined) serveConsent(consent);
  const user = userEvent.setup();
  render(<TenantDetail tenantId="trust-b" />);
  await screen.findByRole('heading', { level: 1, name: 'Sample Area B' });
  if (phase !== undefined) {
    await choose(user, phase);
    await waitFor(() => expect(screen.queryByText('Loading.')).not.toBeInTheDocument());
    // A part that is already completed shows its summary; these tests work on its steps.
    const change = screen.queryByRole('button', { name: /^Change/ });
    if (change !== null) await user.click(change);
  }
  return user;
}
const choose = (user: ReturnType<typeof userEvent.setup>, phase: string) => user.click(within(screen.getByRole('navigation', { name: 'Go live tasks' })).getByRole('link', { name: new RegExp(`^${phase}`) }));
/** The steps shown now. */
const shownSteps = () => Array.from(document.querySelectorAll('[data-el^="OP-STEP-"]')) as HTMLElement[];
/** An element's text with its closed disclosures taken out. */
const bare = (el: HTMLElement) => {
  const clone = el.cloneNode(true) as HTMLElement;
  clone.querySelectorAll('details').forEach((d) => d.remove());
  return clone.textContent ?? '';
};
const lastWrite = () => seenOperatorWrites[seenOperatorWrites.length - 1];
const step = (name: string) => screen.getByRole('region', { name });
/** What a step shows with its closed technical details taken out. */
const headline = (name: string): string => bare(step(name));
const detailsOf = (name: string) => within(Array.from(step(name).querySelectorAll('details')).find((d) => d.querySelector('summary')?.textContent === 'Technical details') as HTMLElement);
const ready = (over: Partial<Detail> = {}): Detail => ({ ...VIEW_DETAIL_READY, ...over });

describe('what the page shows', () => {
  it('has one h1 with the organisation’s name, its status in words, and one h2: the selected part', async () => {
    await open();
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
    expect(screen.getByText('Being set up')).toBeInTheDocument();
    expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual(['Organisation and sign-in']);
    expect(screen.getByText('0 of 5 parts completed')).toBeInTheDocument();
  });

  it('shows the five parts as a task list, each a link with its status in words and a line on where it stands', async () => {
    await open();
    const nav = screen.getByRole('navigation', { name: 'Go live tasks' });
    const items = within(nav).getAllByRole('listitem');
    expect(items).toHaveLength(5);
    items.forEach((li, i) => expect(within(li).getByRole('link').textContent?.replace(/^\d/, '').startsWith(PHASES[i]!)).toBe(true));
    expect(items[0]).toHaveTextContent('In progress');
    expect(items[0]).toHaveTextContent('A Microsoft work account is waiting for you to confirm it.');
    expect(items[1]).toHaveTextContent('Not started');
    expect(items[1]).toHaveTextContent('Connect their Microsoft work accounts first.');
    expect(items[4]).toHaveTextContent('Not started');
  });

  it('marks the selected part with aria-current, opens on the first that is not completed, and moves with the choice', async () => {
    const user = await open(ready({ bindings: VIEW_DETAIL_PROVISIONING.bindings.map((b) => ({ ...b, status: 'verified' as const })) }));
    const nav = screen.getByRole('navigation', { name: 'Go live tasks' });
    const link = (name: string) => within(nav).getByRole('link', { name: new RegExp(`^${name}`) });
    expect(link('Administrator approval')).toHaveAttribute('aria-current', 'step');
    expect(link('Organisation and sign-in')).not.toHaveAttribute('aria-current');
    expect(link('Organisation and sign-in')).toHaveTextContent('Completed');
    expect(screen.getByRole('heading', { level: 2, name: 'Administrator approval' })).toBeInTheDocument();
    await user.click(link('Reach and agreements'));
    expect(link('Reach and agreements')).toHaveAttribute('aria-current', 'step');
    expect(link('Administrator approval')).not.toHaveAttribute('aria-current');
    expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual(['Reach and agreements']);
  });

  it('moves focus to the heading of the part that was chosen', async () => {
    const user = await open();
    await choose(user, 'Teams and people');
    expect(screen.getByRole('heading', { level: 2, name: 'Teams and people' })).toHaveFocus();
  });

  it('has at most one primary button in the selected part, and it is the next thing to do', async () => {
    const user = await open();
    const primaries = () => Array.from(document.querySelectorAll('button[data-variant="primary"]')).map((b) => b.textContent);
    expect(primaries()).toEqual(['Confirm this is their Microsoft account']);
    for (const phase of ['Teams and people', 'Reach and agreements', 'Go live']) {
      await choose(user, phase);
      expect(primaries().length).toBeLessThanOrEqual(1);
    }
    await choose(user, 'Reach and agreements');
    expect(primaries()).toEqual(['Save web address']);
  });

  it('keeps fields to a readable width, in a form of their own', async () => {
    await open(VIEW_DETAIL_PROVISIONING, undefined, 'Reach and agreements');
    const form = screen.getByRole('form', { name: 'Set the web address' });
    expect(form.className).toMatch(/form/);
  });

  it('has no axe violations in any part', async () => {
    const user = await open(VIEW_DETAIL_PROVISIONING, CONSENTED);
    for (const phase of PHASES) {
      await choose(user, phase);
      expect(await runAxe(document.body)).toHaveNoViolations();
    }
  });

  it('says a part is waiting for them while the approval link is out', async () => {
    await open(ready({ bindings: VIEW_DETAIL_PROVISIONING.bindings.map((b) => ({ ...b, status: 'verified' as const })) }), { invitation: { emailMasked: 'j***@example-trust.test', status: 'pending', createdAt: '2026-11-01T09:00:00Z', expiresAt: '2026-11-08T09:00:00Z', consentedAt: null, reason: null } });
    const nav = screen.getByRole('navigation', { name: 'Go live tasks' });
    const item = within(nav).getByRole('link', { name: /^Administrator approval/ }).closest('li') as HTMLElement;
    await waitFor(() => expect(item).toHaveTextContent('Waiting for them'));
    expect(item).toHaveTextContent('Approval link sent. Waiting for their administrator.');
  });

  it('shows a completed part as a short summary with a Change link, and the steps only once Change is chosen', async () => {
    const user = await open(VIEW_DETAIL_READY, CONSENTED);
    await choose(user, 'Teams and people');
    const change = await screen.findByRole('button', { name: /^Change/ });
    const panel = screen.getByRole('region', { name: 'Teams and people' });
    expect(within(panel).getByText('Administrators’ team')).toBeInTheDocument();
    expect(within(panel).getByText('Shift leads')).toBeInTheDocument();
    expect(within(panel).queryByRole('checkbox')).not.toBeInTheDocument();
    expect(within(panel).queryByRole('button', { name: 'Add to team' })).not.toBeInTheDocument();
    await user.click(change);
    expect(await within(panel).findByRole('button', { name: 'Add to team' })).toBeInTheDocument();
  });

  it('confirms the organisation with the NHS code and plain words, and keeps the identifiers under technical details', async () => {
    await open();
    const text = headline('Check the organisation');
    expect(text).toContain('NHS code');
    expect(text).toContain('RYY02');
    expect(text).toContain('Sample Area B Organisation');
    expect(text).toContain('Integrated care board');
    expect(text).toContain('United Kingdom');
    expect(text).toContain('Europe/London');
    expect(text).not.toMatch(/ODS|trust-b/);
    expect(detailsOf('Check the organisation').getByText('trust-b')).toBeInTheDocument();
    expect(detailsOf('Check the organisation').getByText('ODS code')).toBeInTheDocument();
  });

  it('has the technical details as a real disclosure that is closed by default', async () => {
    await open();
    const summary = within(step('Check the organisation')).getByText('Technical details');
    expect(summary.tagName).toBe('SUMMARY');
    expect(summary.closest('details')).not.toHaveAttribute('open');
    expect(screen.queryByText('Details', { exact: true })).not.toBeInTheDocument();
  });

  it('holds every technical identifier under technical details and none on the face of a part, whichever part is chosen', async () => {
    const user = await open(VIEW_DETAIL_PROVISIONING, CONSENTED);
    const ids = ['11111111-1111-4111-8111-111111111111', '22222222-2222-4222-8222-222222222222', 'trust-b', 'ACsampleaccount00000000000000000001'];
    for (const phase of PHASES) {
      await choose(user, phase);
      for (const el of shownSteps()) {
        for (const id of ids) expect(bare(el)).not.toContain(id);
        expect(el.querySelector('details[open]')).toBeNull();
      }
    }
    await choose(user, 'Organisation and sign-in');
    expect(detailsOf('Connect their Microsoft work accounts').getByText('11111111-1111-4111-8111-111111111111')).toBeInTheDocument();
    await choose(user, 'Teams and people');
    expect(detailsOf('Other teams').getByText('22222222-2222-4222-8222-222222222222')).toBeInTheDocument();
    await choose(user, 'Reach and agreements');
    expect(detailsOf('Web address and text number').getByText('ACsampleaccount00000000000000000001')).toBeInTheDocument();
    expect(step('Agreements (recommended)').querySelector('details')).toBeNull();
  });

  it('uses no jargon on the face of any part or of the task list', async () => {
    const user = await open(VIEW_DETAIL_PROVISIONING, CONSENTED);
    const jargon = /\b(directory|Entra|tenant|group object|role mapping|ODS)\b/i;
    for (const phase of PHASES) {
      await choose(user, phase);
      expect(bare(screen.getByRole('region', { name: phase }))).not.toMatch(jargon);
    }
    expect(bare(screen.getByRole('navigation', { name: 'Go live tasks' }))).not.toMatch(jargon);
  });

  it('shows a number with its state and whether it has been tested, and never a secret', async () => {
    await open(VIEW_DETAIL_PROVISIONING, undefined, 'Reach and agreements');
    const list = within(step('Web address and text number')).getByRole('list', { name: 'Text numbers' });
    const row = within(list).getByRole('listitem');
    expect(row).toHaveTextContent('+441632960002 · In use · Not tested');
    expect(document.body.textContent ?? '').not.toMatch(/authTokenRef|tenants\/trust-b|Auth token/);
  });

  it('shows the agreements held', async () => {
    await open(VIEW_DETAIL_PROVISIONING, undefined, 'Reach and agreements');
    const refs = step('Agreements (recommended)');
    expect(within(refs).getByText('DSA-2026-014')).toBeInTheDocument();
    expect(within(refs).getByText(/recommended/, { selector: 'p' })).toBeInTheDocument();
    expect(within(refs).getByText('Clinical safety case', { selector: 'dt' })).toBeInTheDocument();
    expect(within(refs).getAllByText('Not recorded')).toHaveLength(2);
  });

  it('says it could not find the organisation on a 404, and could not load it on another failure', async () => {
    server.use(http.get('/api/bff/platform/tenants/:id', () => HttpResponse.json({ code: 'not-found' }, { status: 404 })));
    const { unmount } = render(<TenantDetail tenantId="trust-x" />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not find that organisation.');
    unmount();
    server.use(http.get('/api/bff/platform/tenants/:id', () => HttpResponse.json({}, { status: 503 })));
    render(<TenantDetail tenantId="trust-x" />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not load the organisation.');
  });

  it('has no axe violations', async () => {
    await open();
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});

describe('Go live', () => {
  it('shows the button only when everything is done and the back end agrees, and asks first', async () => {
    const user = await open(VIEW_DETAIL_READY, CONSENTED);
    await within(step('Go live')).findByRole('button', { name: 'Go live' });
    expect(within(step('Go live')).getByText('Everything is ready. Once it is live, their people can sign in.')).toBeInTheDocument();
    expect(screen.getByText('4 of 5 parts completed')).toBeInTheDocument();
    await user.click(within(step('Go live')).getByRole('button', { name: 'Go live' }));
    const dialog = await screen.findByRole('dialog', { name: 'Go live with this organisation?' });
    await user.click(within(dialog).getByRole('button', { name: 'Yes, go live' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ method: 'POST', path: '/api/bff/platform/tenants/trust-b/activation', csrf: OPERATOR_SAMPLE_CSRF });
    expect(await screen.findByText('The organisation is live.')).toBeInTheDocument();
  });

  it('has the one primary button on the Go live part when it is ready, and none that looks blocked', async () => {
    await open(VIEW_DETAIL_READY, CONSENTED);
    const panel = step('Go live');
    expect(await within(panel).findByRole('button', { name: 'Go live' })).toBeEnabled();
    expect(within(panel).getAllByRole('button')).toHaveLength(1);
  });

  it('has no button, and a short list of what is left by part with a count, while a step is not done', async () => {
    await open(VIEW_DETAIL_PROVISIONING, undefined, 'Go live');
    const card = step('Go live');
    expect(within(card).queryByRole('button', { name: 'Go live' })).not.toBeInTheDocument();
    const left = within(card).getByRole('list', { name: 'Still to do' });
    const lines = within(left).getAllByRole('listitem').map((li) => li.textContent);
    expect(lines).toEqual(['Organisation and sign-in 1 thing left', 'Administrator approval 1 thing left', 'Teams and people 1 thing left', 'Reach and agreements 2 things left']);
  });

  it('never lists the agreements as left, and says they are recommended', async () => {
    await open(VIEW_DETAIL_PROVISIONING, undefined, 'Go live');
    const card = step('Go live');
    expect(bare(card)).not.toMatch(/agreements? (is|are) not|Agreements \(recommended\)/i);
    await waitFor(() => expect(screen.queryByText('Loading.')).not.toBeInTheDocument());
    expect(document.body.textContent ?? '').toContain('Agreements (recommended) 1 of 3');
  });

  it('can go live with no agreement recorded', async () => {
    const none = { dsa: null, dpia: null, dcb0160: null };
    await open({ ...VIEW_DETAIL_READY, tenant: { ...VIEW_DETAIL_READY.tenant, references: none } }, CONSENTED, 'Go live');
    expect(await within(step('Go live')).findByRole('button', { name: 'Go live' })).toBeEnabled();
  });

  it('takes the operator to a part from the list of what is left', async () => {
    const user = await open(VIEW_DETAIL_PROVISIONING, undefined, 'Go live');
    await user.click(within(within(step('Go live')).getByRole('list', { name: 'Still to do' })).getByRole('link', { name: 'Reach and agreements' }));
    expect(screen.getByRole('heading', { level: 2, name: 'Reach and agreements' })).toHaveFocus();
  });

  it.each<[string, () => Detail, unknown]>([
    ['the sign-in is not confirmed', () => ready({ bindings: [{ directoryId: '11111111-1111-4111-8111-111111111111', status: 'pending', verifiedAt: null }] }), CONSENTED],
    ['their administrator has not approved', () => VIEW_DETAIL_READY, { invitation: null }],
    ['their administrators’ team is missing', () => ready({ roleMappings: [{ groupObjectId: '22222222-2222-4222-8222-222222222222', role: 'lead', status: 'active' }] }), CONSENTED],
    ['no other team is added', () => ready({ roleMappings: [{ groupObjectId: '33333333-3333-4333-8333-333333333333', role: 'tenant-admin', status: 'active' }] }), CONSENTED],
    ['the web address is not set', () => ready({ host: null }), CONSENTED],
    ['no number has been tested', () => ready({ numbers: VIEW_DETAIL_READY.numbers.map((n) => ({ ...n, testedAt: null })) }), CONSENTED],
  ])('has no Go live button when %s, and lists what is left', async (_name, make, consent) => {
    await open(make(), consent, 'Go live');
    await screen.findByText(/parts completed/);
    await waitFor(() => expect(screen.queryByText('Loading.')).not.toBeInTheDocument());
    expect(screen.queryByRole('button', { name: 'Go live' })).not.toBeInTheDocument();
    expect(within(step('Go live')).getByRole('list', { name: 'Still to do' })).toBeInTheDocument();
  });

  it('does not make the button look blocked by what only their administrators can do: it says Overwatch will open it', async () => {
    await open(ready({ activation: { ready: false, blockers: ['Area districts set', 'Network agreement accepted'] } }), CONSENTED, 'Go live');
    const card = step('Go live');
    await within(card).findByText('Everything you have to do is done.');
    expect(within(card).queryByRole('list', { name: 'Still to do' })).not.toBeInTheDocument();
    expect(within(card).queryByRole('button')).not.toBeInTheDocument();
    const theirs = within(card).getByRole('list', { name: 'Their administrators finish these' });
    expect(within(theirs).getAllByRole('listitem').map((li) => li.textContent)).toEqual(['Set the area’s districts', 'Accept the network agreement']);
    expect(within(card).getByRole('heading', { name: 'Their administrators finish these after they sign in' })).toBeInTheDocument();
    expect(within(card).getByText('Overwatch will make Go live available when these are done.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /^Go live/ })).toHaveTextContent('Waiting for them');
  });

  it('never shows the back end’s own blocker text, merges blockers that say the same thing, and keeps their administrators’ items apart', async () => {
    const blockers = [
      'Configuration version approved',
      'Time zone set',
      'At least one sender number active with a test text delivered',
      'Email sender verified',
      'Tenant administrator group made and mapped',
      'Sign-in directory bound and verified',
      'At least one role mapping',
      'Support contacts set: coordination phone and clinical safety officer',
      'Retention set for every data class',
      'System, referral system and coordination team names set',
      'Area districts set',
      'Network agreement accepted',
      'Host set',
      'Something nobody has thought of',
    ];
    await open({ ...VIEW_DETAIL_PROVISIONING, activation: { ready: false, blockers } }, undefined, 'Go live');
    const text = document.body.textContent ?? '';
    for (const blocker of blockers) expect(text).not.toContain(blocker);
    expect(text).not.toContain('Number tested');
    const card = step('Go live');
    const lines = within(within(card).getByRole('list', { name: 'Still to do' })).getAllByRole('listitem').map((li) => li.textContent);
    expect(lines).toEqual([
      'Organisation and sign-in 2 things left',
      'Administrator approval 2 things left',
      'Teams and people 2 things left',
      'Reach and agreements 2 things left',
      'Go live 1 thing left',
    ]);
    const theirs = within(within(card).getByRole('list', { name: 'Their administrators finish these' })).getAllByRole('listitem').map((li) => li.textContent);
    expect(theirs).toEqual(['Approve their settings', 'Set the support contacts', 'Set how long records are kept', 'Set the names they use for their systems', 'Set the area’s districts', 'Accept the network agreement']);
    expect(text).not.toContain('No team has been given anything to do yet');
  });

  it('says what is still missing when the back end refuses with a 409', async () => {
    server.use(http.post('/api/bff/platform/tenants/:id/activation', () => HttpResponse.json({ code: 'business-rule' }, { status: 409 })));
    const user = await open(VIEW_DETAIL_READY, CONSENTED);
    await user.click(await within(step('Go live')).findByRole('button', { name: 'Go live' }));
    await user.click(await screen.findByRole('button', { name: 'Yes, go live' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('It cannot go live yet. The page has been read again.');
  });

  it('can be cancelled out of', async () => {
    const user = await open(VIEW_DETAIL_READY, CONSENTED);
    await user.click(await within(step('Go live')).findByRole('button', { name: 'Go live' }));
    await user.click(await screen.findByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(seenOperatorWrites).toEqual([]);
  });

  it('opens a live organisation on Go live, says it is live, and has no Go live button', async () => {
    await open(VIEW_DETAIL_ACTIVE);
    expect(screen.getByRole('heading', { level: 2, name: 'Go live' })).toBeInTheDocument();
    expect(within(step('Go live')).getByText(/This organisation is live since 22 Oct 2026/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Go live' })).not.toBeInTheDocument();
  });

  it('has no axe violations when ready', async () => {
    await open(VIEW_DETAIL_READY, CONSENTED);
    await within(step('Go live')).findByRole('button', { name: 'Go live' });
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});

describe('step 2: connect their sign-in', () => {
  it('confirms the Microsoft account the organisation named, with one button', async () => {
    const user = await open(VIEW_DETAIL_PROVISIONING, undefined, 'Organisation and sign-in');
    await user.click(within(step('Connect their Microsoft work accounts')).getByRole('button', { name: 'Confirm this is their Microsoft account' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ method: 'POST', path: '/api/bff/platform/tenants/trust-b/directory/verification', body: { directoryId: '11111111-1111-4111-8111-111111111111' } });
    expect(lastWrite()?.key).toBeTruthy();
  });

  it('says the connection in words once confirmed, and offers no button', async () => {
    await open(VIEW_DETAIL_READY, CONSENTED, 'Organisation and sign-in');
    const card = step('Connect their Microsoft work accounts');
    expect(within(card).getByText('Connected to Sample Area B’s Microsoft accounts.')).toBeInTheDocument();
    expect(within(card).queryByRole('button', { name: 'Confirm this is their Microsoft account' })).not.toBeInTheDocument();
  });

  it('says nothing is connected when no account is named, and offers no button', async () => {
    await open({ ...VIEW_DETAIL_PROVISIONING, directoryId: null, bindings: [], roleMappings: [] }, undefined, 'Organisation and sign-in');
    const card = step('Connect their Microsoft work accounts');
    expect(within(card).getByText('No Microsoft account is connected yet.', { selector: 'p' })).toBeInTheDocument();
    expect(within(card).queryByRole('button', { name: 'Confirm this is their Microsoft account' })).not.toBeInTheDocument();
  });

  it('looks up their Microsoft account from the domain as a card, and says whether it is the one named, and saves nothing', async () => {
    server.use(http.get('/api/bff/platform/directory-lookup', () => HttpResponse.json({ domain: 'example-trust.test', directoryId: '11111111-1111-4111-8111-111111111111' })));
    const user = await open(VIEW_DETAIL_PROVISIONING, undefined, 'Organisation and sign-in');
    const card = step('Connect their Microsoft work accounts');
    await user.type(within(card).getByLabelText('Their email domain'), 'example-trust.test');
    await user.click(within(card).getByRole('button', { name: 'Look up their Microsoft account' }));
    const found = await waitFor(() => {
      const el = card.querySelector('[data-el="OP-TENANT-DOMAIN-CARD"]');
      expect(el).not.toBeNull();
      return el as HTMLElement;
    });
    expect(found).toHaveTextContent('Found a Microsoft account for example-trust.test.');
    expect(found).toHaveTextContent('It is the same one that is connected here.');
    expect(seenOperatorWrites).toEqual([]);
  });

  it('says when the account found is not the one named, and when none was found', async () => {
    server.use(http.get('/api/bff/platform/directory-lookup', () => HttpResponse.json({ domain: 'other.test', directoryId: '99999999-9999-4999-8999-999999999999' })));
    const user = await open(VIEW_DETAIL_PROVISIONING, undefined, 'Organisation and sign-in');
    const card = step('Connect their Microsoft work accounts');
    await user.type(within(card).getByLabelText('Their email domain'), 'other.test');
    await user.click(within(card).getByRole('button', { name: 'Look up their Microsoft account' }));
    expect(await within(card).findByText('It is not the one that is connected here. Check before you confirm.')).toBeInTheDocument();
    server.use(http.get('/api/bff/platform/directory-lookup', () => HttpResponse.json({ domain: 'nowhere.test', directoryId: null })));
    await user.click(within(card).getByRole('button', { name: 'Look up their Microsoft account' }));
    expect(await within(card).findByText('No Microsoft account was found for nowhere.test. Ask the organisation which one they use.')).toBeInTheDocument();
  });
});

describe('step 3: invite their administrator', () => {
  const invitation = (status: string, extra: Record<string, unknown> = {}) => ({
    invitation: { emailMasked: 'j***@example-trust.test', status, createdAt: '2026-11-01T09:00:00Z', expiresAt: '2026-11-08T09:00:00Z', consentedAt: null, reason: null, ...extra },
  });
  const card = () => step('Ask their administrator to approve');

  it('explains in plain words what approval allows', async () => {
    await open(VIEW_DETAIL_PROVISIONING, undefined, 'Administrator approval');
    expect(card()).toHaveTextContent('Approving lets Overwatch make teams there, add people to them and find people by email address. It does not let Overwatch read anyone’s email or files.');
  });

  it('says no link has been sent, and emails their administrator on a valid address', async () => {
    const user = await open(VIEW_DETAIL_PROVISIONING, undefined, 'Administrator approval');
    expect(await within(card()).findByText('No approval link has been sent yet.')).toBeInTheDocument();
    await user.type(within(card()).getByLabelText('Their administrator’s work email'), 'jane.admin@example-trust.test');
    await user.click(within(card()).getByRole('button', { name: 'Send the approval link to their administrator' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ path: '/api/bff/platform/tenants/trust-b/admin-consent-invitation', body: { email: 'jane.admin@example-trust.test' } });
    expect(await within(card()).findByRole('status')).toHaveTextContent('The approval link was emailed. It works for 7 days. The address is not shown again.');
    expect(within(card()).getByLabelText('Their administrator’s work email')).toHaveValue('');
    expect(document.body.textContent ?? '').not.toContain('jane.admin@example-trust.test');
  });

  it('refuses something that is not an email address before any call', async () => {
    const user = await open(VIEW_DETAIL_PROVISIONING, undefined, 'Administrator approval');
    await user.type(await within(card()).findByLabelText('Their administrator’s work email'), 'not an address');
    await user.click(within(card()).getByRole('button', { name: 'Send the approval link to their administrator' }));
    expect(await within(card()).findByText('Enter the administrator’s work email address, for example name@organisation.nhs.uk.', { selector: 'p' })).toBeInTheDocument();
    expect(seenOperatorWrites).toEqual([]);
  });

  it('says it is waiting for approval, with the masked address, and offers to send the link again', async () => {
    await open(VIEW_DETAIL_PROVISIONING, invitation('pending', { reason: 'Overwatch is not installed in your directory yet.' }), 'Administrator approval');
    expect(await within(card()).findByText(/Waiting for approval\. The link went to j\*\*\*@example-trust\.test and works until/)).toBeInTheDocument();
    expect(within(card()).getByRole('button', { name: 'Send the link again' })).toBeInTheDocument();
    expect(headline('Ask their administrator to approve')).not.toContain('is not installed');
    expect(detailsOf('Ask their administrator to approve').getByText('Overwatch is not installed in your directory yet.')).toBeInTheDocument();
  });

  it('says the link has expired, and offers to send it again', async () => {
    await open(VIEW_DETAIL_PROVISIONING, invitation('expired'), 'Administrator approval');
    expect(await within(card()).findByText('The approval link has expired. Send a new one.')).toBeInTheDocument();
    expect(within(card()).getByRole('button', { name: 'Send the link again' })).toBeInTheDocument();
  });

  it('says it is approved, and offers no form', async () => {
    const user = await open(VIEW_DETAIL_PROVISIONING, invitation('consented', { consentedAt: '2026-11-02T10:00:00Z' }));
    await choose(user, 'Administrator approval');
    const panel = screen.getByRole('region', { name: 'Administrator approval' });
    expect(await within(panel).findByText(/2 Nov 2026/)).toBeInTheDocument();
    expect(within(panel).getByText('Approved')).toBeInTheDocument();
    expect(within(panel).queryByRole('button')).not.toBeInTheDocument();
  });

  it('does not offer the form until their sign-in is connected', async () => {
    await open({ ...VIEW_DETAIL_PROVISIONING, bindings: [] }, undefined, 'Administrator approval');
    expect(await within(card()).findByText('Connect their Microsoft work accounts first. The approval link is for their Microsoft account.')).toBeInTheDocument();
    expect(within(card()).queryByRole('button', { name: /Send/ })).not.toBeInTheDocument();
  });

  it('says it could not be sent, without the address, when the back end refuses', async () => {
    server.use(http.post('/api/bff/platform/tenants/:id/admin-consent-invitation', () => HttpResponse.json({ code: 'conflict' }, { status: 409 })));
    const user = await open(VIEW_DETAIL_PROVISIONING, undefined, 'Administrator approval');
    await user.type(await within(card()).findByLabelText('Their administrator’s work email'), 'jane.admin@example-trust.test');
    await user.click(within(card()).getByRole('button', { name: 'Send the approval link to their administrator' }));
    expect(await within(card()).findByRole('alert')).toHaveTextContent('The link could not be sent. Connect their Microsoft work accounts first, and check that Overwatch can send email.');
  });
});

describe('step 4: their administrators’ team', () => {
  const card = () => step('Administrators’ team');
  const withAdmin = ready();

  it('offers nothing until their administrator has approved', async () => {
    await open(VIEW_DETAIL_PROVISIONING, undefined, 'Teams and people');
    expect(await within(card()).findByText('You can create their administrators’ team once their administrator has approved Overwatch.')).toBeInTheDocument();
    expect(within(card()).queryByRole('button')).not.toBeInTheDocument();
  });

  it('explains that this team is the only route to administrator rights', async () => {
    await open(VIEW_DETAIL_PROVISIONING, undefined, 'Teams and people');
    expect(card()).toHaveTextContent('The administrators’ team is the only way anyone gets administrator rights in Overwatch.');
  });

  it('creates the team once, sending no roles and no name, and lists what was made under Details', async () => {
    const user = await open(VIEW_DETAIL_PROVISIONING, CONSENTED, 'Teams and people');
    await user.click(await within(card()).findByRole('button', { name: 'Create their administrators’ team' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ method: 'POST', path: '/api/bff/platform/tenants/trust-b/entra-groups', csrf: OPERATOR_SAMPLE_CSRF, body: { roles: [] } });
    expect(lastWrite()?.key).toBeTruthy();
    expect(await within(card()).findByText('Their administrators’ team is in place.')).toBeInTheDocument();
    expect(detailsOf('Administrators’ team').getByRole('row', { name: /Administrators RXX01_overwatch_tenant-admin Made now/ })).toBeInTheDocument();
    expect(headline('Administrators’ team')).not.toContain('RXX01_overwatch');
  });

  it('says the directory could not be reached, in words', async () => {
    server.use(http.post('/api/bff/platform/tenants/:id/entra-groups', () => HttpResponse.json({ code: 'transient' }, { status: 503 })));
    const user = await open(VIEW_DETAIL_PROVISIONING, CONSENTED, 'Teams and people');
    await user.click(await within(card()).findByRole('button', { name: 'Create their administrators’ team' }));
    expect(await within(card()).findByRole('alert')).toHaveTextContent('Their Microsoft account could not be reached. Try again in a minute.');
  });

  it('once the team exists, says so and adds the first administrator by email, never showing or keeping the address', async () => {
    const user = await open(withAdmin, CONSENTED, 'Teams and people');
    expect(await within(card()).findByText('Their administrators’ team is added to Overwatch.')).toBeInTheDocument();
    expect(within(card()).queryByRole('button', { name: 'Create their administrators’ team' })).not.toBeInTheDocument();
    await user.type(within(card()).getByLabelText('Administrator’s work email'), 'jane.member@example-trust.test');
    await user.click(within(card()).getByRole('button', { name: 'Add the first administrator by email' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ path: '/api/bff/platform/tenants/trust-b/entra-groups/members', body: { role: 'tenant-admin', email: 'jane.member@example-trust.test' } });
    expect(await within(card()).findByRole('status')).toHaveTextContent('Added to the team. The address is not kept.');
    expect(within(card()).getByLabelText('Administrator’s work email')).toHaveValue('');
    expect(document.body.textContent ?? '').not.toContain('jane.member@example-trust.test');
  });

  it('refuses a non-address first, and says no one has that address when their Microsoft account does not know it', async () => {
    server.use(http.post('/api/bff/platform/tenants/:id/entra-groups/members', () => HttpResponse.json({ code: 'invalid' }, { status: 400 })));
    const user = await open(withAdmin, CONSENTED, 'Teams and people');
    await user.type(await within(card()).findByLabelText('Administrator’s work email'), 'nonsense');
    await user.click(within(card()).getByRole('button', { name: 'Add the first administrator by email' }));
    expect(await within(card()).findByText('Enter the person’s work email address, for example name@organisation.nhs.uk.', { selector: 'p' })).toBeInTheDocument();
    expect(seenOperatorWrites).toEqual([]);
    await user.clear(within(card()).getByLabelText('Administrator’s work email'));
    await user.type(within(card()).getByLabelText('Administrator’s work email'), 'ghost@example-trust.test');
    await user.click(within(card()).getByRole('button', { name: 'Add the first administrator by email' }));
    expect(await within(card()).findByRole('alert')).toHaveTextContent('No one in their Microsoft accounts has that email address.');
  });

  it('has no first administrator section by another name, and no mobile invitation', async () => {
    await open(VIEW_DETAIL_PROVISIONING, undefined, 'Teams and people');
    expect(screen.queryByRole('region', { name: 'First administrator' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Send invitation' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Mobile number')).not.toBeInTheDocument();
  });

  it('has no axe violations once approved', async () => {
    await open(withAdmin, CONSENTED, 'Teams and people');
    await within(card()).findByRole('button', { name: 'Add the first administrator by email' });
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});

describe('step 5: who can do what', () => {
  const card = () => step('Other teams');

  it('lists the six teams in plain words with what each can do, each added to Overwatch only when it exists', async () => {
    await open(VIEW_DETAIL_PROVISIONING, undefined, 'Teams and people');
    const list = within(card()).getAllByRole('listitem');
    expect(list.map((li) => li.querySelector('strong')?.textContent)).toEqual(['Advisors', 'Shift leads', 'Clinical leads', 'Planning', 'Audit', 'Criteria owners']);
    expect(within(list[1]!).getByText('Added to Overwatch')).toBeInTheDocument();
    expect(within(list[0]!).getByText('Not added yet')).toBeInTheDocument();
    expect(list[4]).toHaveTextContent('They cannot change anything.');
  });

  it('says the administrators’ team is the only route to administrator rights', async () => {
    await open(VIEW_DETAIL_PROVISIONING, undefined, 'Teams and people');
    expect(card()).toHaveTextContent('The administrators’ team above is the only route to administrator rights: none of these teams gives them.');
  });

  it('offers nothing to tick until their administrator has approved', async () => {
    await open(VIEW_DETAIL_PROVISIONING, undefined, 'Teams and people');
    expect(await within(card()).findByText('Teams can be added once their administrator has approved Overwatch.')).toBeInTheDocument();
    expect(within(card()).queryByRole('checkbox')).not.toBeInTheDocument();
    expect(within(card()).queryByRole('button', { name: 'Add the ticked teams' })).not.toBeInTheDocument();
  });

  it('adds the teams that were ticked, sending only roles (no name, no group id), and says so', async () => {
    const user = await open(VIEW_DETAIL_PROVISIONING, CONSENTED, 'Teams and people');
    const add = await within(card()).findByRole('button', { name: 'Add the ticked teams' });
    expect(add).toBeDisabled();
    expect(within(card()).queryByRole('checkbox', { name: 'Shift leads' })).not.toBeInTheDocument();
    await user.click(within(card()).getByRole('checkbox', { name: 'Advisors' }));
    await user.click(within(card()).getByRole('checkbox', { name: 'Audit' }));
    await user.click(add);
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ method: 'POST', path: '/api/bff/platform/tenants/trust-b/entra-groups', csrf: OPERATOR_SAMPLE_CSRF, body: { roles: ['advisor', 'audit'] } });
    expect(await within(card()).findByText('The teams are added to Overwatch.')).toBeInTheDocument();
  });

  it('adds a person to an added team by email, offering only teams that exist', async () => {
    const user = await open(VIEW_DETAIL_PROVISIONING, CONSENTED, 'Teams and people');
    const select = await within(card()).findByRole('combobox', { name: 'Team' });
    expect(within(select).getAllByRole('option').map((o) => o.textContent)).toEqual(['Shift leads']);
    await user.type(within(card()).getByLabelText('Person’s work email'), 'sam.lead@example-trust.test');
    await user.click(within(card()).getByRole('button', { name: 'Add to team' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ path: '/api/bff/platform/tenants/trust-b/entra-groups/members', body: { role: 'lead', email: 'sam.lead@example-trust.test' } });
    expect(await within(card()).findByRole('status')).toHaveTextContent('Added to the team. The address is not kept.');
    expect(document.body.textContent ?? '').not.toContain('sam.lead@example-trust.test');
  });

  it('says a team already giving a different role was not changed, on a 409', async () => {
    server.use(http.post('/api/bff/platform/tenants/:id/entra-groups', () => HttpResponse.json({ code: 'conflict' }, { status: 409 })));
    const user = await open(VIEW_DETAIL_PROVISIONING, CONSENTED, 'Teams and people');
    await user.click(await within(card()).findByRole('checkbox', { name: 'Planning' }));
    await user.click(within(card()).getByRole('button', { name: 'Add the ticked teams' }));
    expect(await within(card()).findByRole('alert')).toHaveTextContent('A team already gives a different role. Nothing was changed.');
  });
});

describe('step 6: how people reach them', () => {
  const card = () => step('Web address and text number');

  it('sets the web address', async () => {
    const user = await open(VIEW_DETAIL_PROVISIONING, undefined, 'Reach and agreements');
    await user.type(within(card()).getByLabelText('Web address'), 'tenant-b.example.test');
    await user.click(within(card()).getByRole('button', { name: 'Save web address' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ method: 'PUT', path: '/api/bff/platform/tenants/trust-b/host', csrf: OPERATOR_SAMPLE_CSRF, body: { host: 'tenant-b.example.test' } });
    expect(lastWrite()?.key).toBeTruthy();
    expect(await within(card()).findByText('Web address saved.')).toBeInTheDocument();
  });

  it('says the web address in words once set', async () => {
    await open(VIEW_DETAIL_READY, CONSENTED, 'Reach and agreements');
    expect(within(card()).getByText('Their web address is tenant-b.example.test.')).toBeInTheDocument();
  });

  it('records a text number in international form with the sender name, and refuses one that is not', async () => {
    const user = await open(VIEW_DETAIL_PROVISIONING, undefined, 'Reach and agreements');
    await user.type(within(card()).getByLabelText('Text number'), '01632 960003');
    await user.type(within(card()).getByLabelText('Text account'), 'ACsample2');
    await user.type(within(card()).getByLabelText('Sender name'), 'SampleB');
    await user.click(within(card()).getByRole('button', { name: 'Record text number' }));
    expect(await within(card()).findByText('Enter the number in international form, for example +441632960003.', { selector: 'p' })).toBeInTheDocument();
    expect(seenOperatorWrites).toEqual([]);
    const number = within(card()).getByLabelText('Text number');
    await user.clear(number);
    await user.type(number, '+441632960003');
    await user.click(within(card()).getByRole('button', { name: 'Record text number' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ method: 'POST', path: '/api/bff/platform/tenants/trust-b/numbers', body: { e164: '+441632960003', accountSid: 'ACsample2', senderLabel: 'SampleB' } });
  });

  it('has no axe violations on the text number part, with a number, the shared line and the confirm step', async () => {
    const user = await open({ ...VIEW_DETAIL_PROVISIONING, sharedLine: { status: 'active', testedAt: null } }, undefined, 'Reach and agreements');
    await user.click(within(card()).getByRole('button', { name: 'Stop using +441632960002' }));
    expect(await runAxe(document.body)).toHaveNoViolations();
  });

  it('has no way to mark a number as tested by hand', async () => {
    await open(VIEW_DETAIL_PROVISIONING, undefined, 'Reach and agreements');
    expect(within(card()).queryByRole('button', { name: /Mark .* as tested/ })).not.toBeInTheDocument();
  });

  it('sends a test text from the number to the mobile typed, says the provider accepted it, and never shows the mobile again', async () => {
    const user = await open(VIEW_DETAIL_PROVISIONING, undefined, 'Reach and agreements');
    const form = within(card()).getByRole('form', { name: 'Send a test text from +441632960002' });
    await user.type(within(form).getByLabelText('Mobile phone to send the test to'), '07700 900456');
    await user.click(within(form).getByRole('button', { name: 'Send a test text' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ method: 'POST', path: '/api/bff/platform/tenants/trust-b/numbers/test-text', body: { e164: '+441632960002', to: '07700 900456' } });
    expect(await within(form).findByRole('status')).toHaveTextContent('Test text sent. This line is now marked as tested because the text provider accepted the text.');
    expect(within(form).getByLabelText('Mobile phone to send the test to')).toHaveValue('');
    expect(document.body.textContent ?? '').not.toContain('07700 900456');
  });

  it('refuses a test text to something that is not a UK mobile before sending anything', async () => {
    const user = await open(VIEW_DETAIL_PROVISIONING, undefined, 'Reach and agreements');
    const form = within(card()).getByRole('form', { name: 'Send a test text from +441632960002' });
    await user.type(within(form).getByLabelText('Mobile phone to send the test to'), '01632 960001');
    await user.click(within(form).getByRole('button', { name: 'Send a test text' }));
    expect(await within(form).findByText('Enter a UK mobile number, like 07700 900456.')).toBeInTheDocument();
    expect(seenOperatorWrites).toEqual([]);
  });

  it.each([
    [409, 'The organisation’s text account is not set up yet.'],
    [422, 'The text could not be sent to that number. Check it is a UK mobile number.'],
    [503, 'The text service is busy. Try again in a moment.'],
    [500, 'The test text could not be sent. Try again.'],
  ])('says in words why a test text was not sent, on a %i', async (status, words) => {
    server.use(http.post('/api/bff/platform/tenants/:id/numbers/test-text', () => HttpResponse.json({}, { status })));
    const user = await open(VIEW_DETAIL_PROVISIONING, undefined, 'Reach and agreements');
    const form = within(card()).getByRole('form', { name: 'Send a test text from +441632960002' });
    await user.type(within(form).getByLabelText('Mobile phone to send the test to'), '07700 900456');
    await user.click(within(form).getByRole('button', { name: 'Send a test text' }));
    expect(await within(form).findByRole('alert')).toHaveTextContent(words);
    expect(document.body.textContent ?? '').not.toContain('07700 900456');
  });

  it('stops using a number only after a confirm step, and says the number stays held', async () => {
    const user = await open(VIEW_DETAIL_PROVISIONING, undefined, 'Reach and agreements');
    await user.click(within(card()).getByRole('button', { name: 'Stop using +441632960002' }));
    expect(seenOperatorWrites).toEqual([]);
    const confirm = within(card()).getByRole('group', { name: 'Stop using +441632960002' });
    expect(confirm).toHaveTextContent('no other organisation can take it');
    await user.click(within(confirm).getByRole('button', { name: 'Keep using it' }));
    expect(seenOperatorWrites).toEqual([]);
    await user.click(within(card()).getByRole('button', { name: 'Stop using +441632960002' }));
    await user.click(within(within(card()).getByRole('group', { name: 'Stop using +441632960002' })).getByRole('button', { name: 'Yes, stop using it' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ method: 'POST', path: '/api/bff/platform/tenants/trust-b/numbers/retire', body: { e164: '+441632960002' } });
  });

  it('says a stopped number is held, offers nothing to do with it, and counts it for nothing', async () => {
    const stopped = { ...VIEW_DETAIL_READY, numbers: VIEW_DETAIL_READY.numbers.map((n) => ({ ...n, status: 'retired' })), activation: { ready: false, blockers: ['At least one sender number active with a test text delivered'] } };
    await open(stopped, CONSENTED, 'Reach and agreements');
    expect(within(card()).getByRole('listitem')).toHaveTextContent('Stopped');
    expect(within(card()).queryByRole('button', { name: /Stop using|Send a test text/ })).not.toBeInTheDocument();
    expect(within(card()).getByText(/held for this organisation/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /^Reach and agreements/ })).toHaveTextContent('Text number not tested');
  });

  it('chooses the shared line for sending, and says plainly what it cannot do', async () => {
    const user = await open(VIEW_DETAIL_PROVISIONING, undefined, 'Reach and agreements');
    expect(within(card()).getByText(/People cannot reply by text until the organisation has its own number\./)).toBeInTheDocument();
    await user.click(within(card()).getByRole('button', { name: 'Use Overwatch’s shared line (sending only)' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ method: 'POST', path: '/api/bff/platform/tenants/trust-b/numbers/shared', body: {} });
  });

  it('tests the shared line, and counts it only once a test text has been sent on it', async () => {
    const untested = { ...VIEW_DETAIL_PROVISIONING, numbers: [], sharedLine: { status: 'active', testedAt: null } };
    const user = await open(untested, undefined, 'Reach and agreements');
    expect(screen.getByRole('link', { name: /^Reach and agreements/ })).toHaveTextContent('Text number not tested');
    const form = within(card()).getByRole('form', { name: 'Send a test text from the shared line' });
    await user.type(within(form).getByLabelText('Mobile phone to send the test to'), '07700 900456');
    await user.click(within(form).getByRole('button', { name: 'Send a test text' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ path: '/api/bff/platform/tenants/trust-b/numbers/test-text', body: { to: '07700 900456' } });
    expect(lastWrite()?.body).not.toHaveProperty('e164');
  });

  it('counts a tested shared line as a tested text number', async () => {
    const tested = { ...VIEW_DETAIL_PROVISIONING, numbers: [], sharedLine: { status: 'active', testedAt: '2026-10-21T10:00:00Z' } };
    await open(tested, undefined, 'Reach and agreements');
    expect(screen.getByRole('link', { name: /^Reach and agreements/ })).toHaveTextContent('Text number tested');
  });

  it('says a web address or number another organisation holds could not be saved, on a 409', async () => {
    server.use(http.put('/api/bff/platform/tenants/:id/host', () => HttpResponse.json({ code: 'conflict' }, { status: 409 })));
    const user = await open(VIEW_DETAIL_PROVISIONING, undefined, 'Reach and agreements');
    await user.type(within(card()).getByLabelText('Web address'), 'taken.example.test');
    await user.click(within(card()).getByRole('button', { name: 'Save web address' }));
    expect(await within(card()).findByRole('alert')).toHaveTextContent('That web address is used by another organisation.');
  });

  it('says a write could not be made, and keeps what was typed', async () => {
    server.use(http.put('/api/bff/platform/tenants/:id/host', () => HttpResponse.json({}, { status: 503 })));
    const user = await open(VIEW_DETAIL_PROVISIONING, undefined, 'Reach and agreements');
    await user.type(within(card()).getByLabelText('Web address'), 'tenant-b.example.test');
    await user.click(within(card()).getByRole('button', { name: 'Save web address' }));
    expect(await within(card()).findByRole('alert')).toHaveTextContent('The web address could not be saved. Try again.');
    expect(within(card()).getByLabelText('Web address')).toHaveValue('tenant-b.example.test');
  });
});

describe('step 7: agreements', () => {
  it('records the references that were filled in and needs at least one', async () => {
    const user = await open(VIEW_DETAIL_PROVISIONING, undefined, 'Reach and agreements');
    const card = step('Agreements (recommended)');
    await user.click(within(card).getByRole('button', { name: 'Save agreements' }));
    expect(await within(card).findByText('Enter at least one reference.')).toBeInTheDocument();
    expect(seenOperatorWrites).toEqual([]);
    await user.type(within(card).getByLabelText('Data sharing agreement'), 'DSA-2026-015');
    await user.type(within(card).getByLabelText('Clinical safety case'), 'DCB-9');
    await user.click(within(card).getByRole('button', { name: 'Save agreements' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ method: 'PUT', path: '/api/bff/platform/tenants/trust-b/references', body: { dsaRef: 'DSA-2026-015', dcb0160Ref: 'DCB-9' } });
    expect(await within(card).findByText('Agreements saved.')).toBeInTheDocument();
  });
});

describe('suspending, resuming and starting to close', () => {
  it('suspends a live organisation with a mode and a reason, after a dialog that says what each mode does', async () => {
    const user = await open(VIEW_DETAIL_ACTIVE);
    await user.click(screen.getByRole('button', { name: 'Suspend' }));
    const dialog = await screen.findByRole('dialog', { name: 'Suspend this organisation?' });
    expect(within(dialog).getByText('Read only: people can look but nobody can change anything.')).toBeInTheDocument();
    expect(within(dialog).getByText('Blocked: nobody can sign in. Use this for a security incident.')).toBeInTheDocument();
    await user.click(within(dialog).getByRole('radio', { name: /Blocked/ }));
    await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Reason' }), 'security-incident');
    await user.click(within(dialog).getByRole('button', { name: 'Confirm suspension' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ method: 'POST', path: '/api/bff/platform/tenants/trust-b/suspension', body: { mode: 'blocked', reason: 'security-incident' } });
    expect(await screen.findByText('The organisation is suspended.')).toBeInTheDocument();
  });

  it('refuses a suspension with no reason chosen', async () => {
    const user = await open(VIEW_DETAIL_ACTIVE);
    await user.click(screen.getByRole('button', { name: 'Suspend' }));
    await user.click(await screen.findByRole('button', { name: 'Confirm suspension' }));
    expect(await screen.findByText('Choose a reason.')).toBeInTheDocument();
    expect(seenOperatorWrites).toEqual([]);
  });

  it('shows a suspended organisation’s mode, reason and time, and resumes it after a dialog', async () => {
    const user = await open(VIEW_DETAIL_SUSPENDED);
    expect(screen.getByText('Suspended read only since 25 Oct 2026, 09:00. Reason: contract.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Resume' }));
    await user.click(await screen.findByRole('button', { name: 'Confirm resume' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ method: 'DELETE', path: '/api/bff/platform/tenants/trust-b/suspension' });
    expect(await screen.findByText('The organisation is resumed. 3 services were prompted and 1 announced.')).toBeInTheDocument();
  });

  it('offers no suspension to an organisation that is not live, and no resume to one that is not suspended', async () => {
    await open(VIEW_DETAIL_PROVISIONING);
    expect(screen.queryByRole('button', { name: 'Suspend' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Resume' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Start closing the organisation' })).not.toBeInTheDocument();
  });

  it('warns that closing starts at once and the export is not built, and needs the organisation’s own id typed', async () => {
    const user = await open(VIEW_DETAIL_ACTIVE);
    await user.click(screen.getByRole('button', { name: 'Start closing the organisation' }));
    const dialog = await screen.findByRole('dialog', { name: 'Start closing this organisation?' });
    expect(within(dialog).getByText(/Its people cannot sign in from now on/)).toBeInTheDocument();
    expect(within(dialog).getByText(/Exporting its data is not built yet/)).toBeInTheDocument();
    const confirm = within(dialog).getByRole('button', { name: 'Start closing' });
    expect(confirm).toBeDisabled();
    const field = () => within(dialog).getByLabelText('Type the organisation id to confirm (shown under Technical details in Organisation and sign-in)');
    await user.type(field(), 'trust-a');
    expect(confirm).toBeDisabled();
    await user.clear(field());
    await user.type(field(), 'trust-b');
    expect(confirm).toBeEnabled();
    await user.click(confirm);
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ method: 'POST', path: '/api/bff/platform/tenants/trust-b/offboarding', body: { confirm: 'trust-b' } });
    expect(await screen.findByText('Closing has started. The notice ends 29 Nov 2026, 09:00.')).toBeInTheDocument();
  });
});

describe('a step that was done and could not be recorded', () => {
  it('says so, as an alert, and does not offer the step again', async () => {
    server.use(http.post('/api/bff/platform/tenants/:id/suspension', () => HttpResponse.json({ mode: 'read-only', recorded: false })));
    const user = await open(VIEW_DETAIL_ACTIVE);
    await user.click(screen.getByRole('button', { name: 'Suspend' }));
    await user.selectOptions(await screen.findByRole('combobox', { name: 'Reason' }), 'contract');
    await user.click(screen.getByRole('button', { name: 'Confirm suspension' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The step was done, but the platform record could not be written. Do not repeat it. Tell the person who looks after the platform record.');
  });
});
