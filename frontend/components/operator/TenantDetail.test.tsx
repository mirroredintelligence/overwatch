import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { CONSENTED, VIEW_DETAIL_ACTIVE, VIEW_DETAIL_PROVISIONING, VIEW_DETAIL_READY, VIEW_DETAIL_SUSPENDED } from '@/test/fixtures/operator';
import { OPERATOR_SAMPLE_CSRF, resetOperatorWrites, seenOperatorWrites } from '@/test/msw/handlers/operator';
import { server } from '@/test/msw/server';
import { TenantDetail } from './TenantDetail';

// One partner organisation's page (TEN-083) as a guided "Go live" funnel: eight steps in order, each with one next
// action and its identifiers under Details; Go live only when every step is done. Every write is the operator's own,
// with its CSRF token and one idempotency key per submit, and is the same write as before the funnel. A step that was
// done and not recorded by the platform chain is said so, and is never offered again. No secret is ever shown.

beforeEach(() => resetOperatorWrites());

type Detail = typeof VIEW_DETAIL_READY;
const serveConsent = (body: unknown) => server.use(http.get('/api/bff/platform/tenants/:id/admin-consent', () => HttpResponse.json(body as Record<string, unknown>)));
function serve(detail: unknown) {
  server.use(http.get('/api/bff/platform/tenants/:id', () => HttpResponse.json(detail as Record<string, unknown>)));
}
async function open(detail: unknown = VIEW_DETAIL_PROVISIONING, consent?: unknown) {
  serve(detail);
  if (consent !== undefined) serveConsent(consent);
  const user = userEvent.setup();
  render(<TenantDetail tenantId="trust-b" />);
  await screen.findByRole('heading', { level: 1, name: 'Sample Area B' });
  return user;
}
const lastWrite = () => seenOperatorWrites[seenOperatorWrites.length - 1];
const step = (name: string) => screen.getByRole('region', { name });
/** What a step shows with its collapsed Details taken out. */
function headline(name: string): string {
  const clone = step(name).cloneNode(true) as HTMLElement;
  clone.querySelectorAll('details').forEach((d) => d.remove());
  return clone.textContent ?? '';
}
const detailsOf = (name: string) => within(step(name).querySelector('details') as HTMLElement);
const ready = (over: Partial<Detail> = {}): Detail => ({ ...VIEW_DETAIL_READY, ...over });
const withRefs = (refs: Partial<Detail['tenant']['references']>): Detail => ({ ...VIEW_DETAIL_READY, tenant: { ...VIEW_DETAIL_READY.tenant, references: { ...VIEW_DETAIL_READY.tenant.references, ...refs } } });

const TITLES = ['Confirm the organisation', 'Connect their sign-in', 'Invite their administrator', 'Set up their administrators’ team', 'Who can do what', 'How people reach them', 'Agreements', 'Go live'];

describe('what the page shows', () => {
  it('has one h1 with the organisation’s name, its status in words, and the headings of the steps in order', async () => {
    await open();
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
    expect(screen.getByText('Being set up')).toBeInTheDocument();
    expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual(TITLES);
  });

  it('shows the progress as a list of the eight steps, each with its state in a word, and says which is next', async () => {
    await open();
    const nav = screen.getByRole('navigation', { name: 'Go live progress' });
    const items = within(nav).getAllByRole('listitem');
    expect(items).toHaveLength(8);
    expect(items[0]).toHaveTextContent('1. Confirm the organisation');
    expect(items[0]).toHaveTextContent('Done');
    expect(items[1]).toHaveTextContent('2. Connect their sign-in');
    expect(items[1]).toHaveTextContent('Next');
    expect(items[1]).toHaveAttribute('aria-current', 'step');
    expect(items[2]).toHaveTextContent('To do');
    expect(screen.getByText('2 of 8 steps done')).toBeInTheDocument();
  });

  it('names the next step in one line, with a link to it', async () => {
    await open();
    expect(screen.getByRole('link', { name: 'Connect their sign-in', description: '' })).toHaveAttribute('href', '#step-signin');
    expect(document.querySelector('[data-el="OP-NEXT-STEP"]')).toHaveTextContent('Next: Connect their sign-in');
  });

  it('moves the next step on as steps are done', async () => {
    await open(ready({ bindings: VIEW_DETAIL_PROVISIONING.bindings.map((b) => ({ ...b, status: 'verified' as const })) }));
    expect(document.querySelector('[data-el="OP-NEXT-STEP"]')).toHaveTextContent('Next: Invite their administrator');
  });

  it('confirms the organisation with the NHS code and plain words, and keeps the identifiers under Details', async () => {
    await open();
    const text = headline('Confirm the organisation');
    expect(text).toContain('NHS code');
    expect(text).toContain('RYY02');
    expect(text).toContain('Sample Area B Organisation');
    expect(text).toContain('Integrated care board');
    expect(text).toContain('United Kingdom');
    expect(text).toContain('Europe/London');
    expect(text).not.toMatch(/ODS|trust-b/);
    expect(detailsOf('Confirm the organisation').getByText('trust-b')).toBeInTheDocument();
    expect(detailsOf('Confirm the organisation').getByText('ODS code')).toBeInTheDocument();
  });

  it('holds every technical identifier under Details and none in the headline of a step', async () => {
    await open(VIEW_DETAIL_PROVISIONING, CONSENTED);
    const ids = ['11111111-1111-4111-8111-111111111111', '22222222-2222-4222-8222-222222222222', 'trust-b', 'ACsampleaccount00000000000000000001'];
    for (const name of TITLES) {
      for (const id of ids) expect(headline(name)).not.toContain(id);
    }
    expect(detailsOf('Connect their sign-in').getByText('11111111-1111-4111-8111-111111111111')).toBeInTheDocument();
    expect(detailsOf('Who can do what').getByText('22222222-2222-4222-8222-222222222222')).toBeInTheDocument();
    expect(detailsOf('How people reach them').getByText('ACsampleaccount00000000000000000001')).toBeInTheDocument();
    expect(detailsOf('Confirm the organisation').getByText('trust-b')).toBeInTheDocument();
    for (const name of TITLES.slice(0, 7)) expect(step(name).querySelector('details[open]')).toBeNull();
    expect(step('Agreements').querySelector('details')).toBeNull();
  });

  it('uses no jargon in what a step says on its face', async () => {
    await open(VIEW_DETAIL_PROVISIONING, CONSENTED);
    for (const name of TITLES) expect(headline(name)).not.toMatch(/\b(directory|Entra|tenant|group object|role mapping|ODS)\b/i);
  });

  it('shows a number with its state and whether it has been tested, and never a secret', async () => {
    await open();
    const table = within(step('How people reach them')).getByRole('table', { name: 'Text numbers' });
    const row = within(table).getByRole('row', { name: /\+441632960002/ });
    expect(within(row).getByText('In use')).toBeInTheDocument();
    expect(within(row).getByText('Not tested')).toBeInTheDocument();
    expect(document.body.textContent ?? '').not.toMatch(/authTokenRef|tenants\/trust-b|Auth token/);
  });

  it('shows the agreements held', async () => {
    await open();
    const refs = step('Agreements');
    expect(within(refs).getByText('DSA-2026-014')).toBeInTheDocument();
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
  it('shows the button only when every step is done and the back end agrees, and asks first', async () => {
    const user = await open(VIEW_DETAIL_READY, CONSENTED);
    await within(step('Go live')).findByRole('button', { name: 'Go live' });
    expect(within(step('Go live')).getByText('Every step is done. Once it is live, their people can sign in.')).toBeInTheDocument();
    expect(screen.getByText('7 of 8 steps done')).toBeInTheDocument();
    await user.click(within(step('Go live')).getByRole('button', { name: 'Go live' }));
    const dialog = await screen.findByRole('dialog', { name: 'Go live with this organisation?' });
    await user.click(within(dialog).getByRole('button', { name: 'Yes, go live' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ method: 'POST', path: '/api/bff/platform/tenants/trust-b/activation', csrf: OPERATOR_SAMPLE_CSRF });
    expect(await screen.findByText('The organisation is live.')).toBeInTheDocument();
  });

  it('has no button, and lists what is missing in plain words, while a step is not done', async () => {
    await open();
    const card = step('Go live');
    expect(within(card).queryByRole('button', { name: 'Go live' })).not.toBeInTheDocument();
    const missing = within(card).getByRole('list', { name: 'Still to do' });
    const lines = within(missing).getAllByRole('listitem').map((li) => li.textContent);
    expect(lines).toContain('Their Microsoft work accounts are not connected and confirmed yet. (Connect their sign-in, step 2)');
    expect(lines).toContain('The web address is not set. (How people reach them, step 6)');
    expect(lines).toContain('A text number has not been tested yet. (How people reach them, step 6)');
  });

  it.each<[string, () => Detail, unknown]>([
    ['the sign-in is not confirmed', () => ready({ bindings: [{ directoryId: '11111111-1111-4111-8111-111111111111', status: 'pending', verifiedAt: null }] }), CONSENTED],
    ['their administrator has not approved', () => VIEW_DETAIL_READY, { invitation: null }],
    ['their administrators’ team is missing', () => ready({ roleMappings: [{ groupObjectId: '22222222-2222-4222-8222-222222222222', role: 'lead', status: 'active' }] }), CONSENTED],
    ['no other team is added', () => ready({ roleMappings: [{ groupObjectId: '33333333-3333-4333-8333-333333333333', role: 'tenant-admin', status: 'active' }] }), CONSENTED],
    ['the web address is not set', () => ready({ host: null }), CONSENTED],
    ['no number has been tested', () => ready({ numbers: VIEW_DETAIL_READY.numbers.map((n) => ({ ...n, testedAt: null })) }), CONSENTED],
    ['an agreement is missing', () => withRefs({ dpia: null }), CONSENTED],
    ['the back end is not ready', () => ready({ activation: { ready: false, blockers: ['Area districts set'] } }), CONSENTED],
  ])('has no Go live button when %s', async (_name, make, consent) => {
    await open(make(), consent);
    await screen.findByText(/steps done/);
    await waitFor(() => expect(screen.queryByText('Loading.')).not.toBeInTheDocument());
    expect(screen.queryByRole('button', { name: 'Go live' })).not.toBeInTheDocument();
    expect(within(step('Go live')).getByRole('list', { name: 'Still to do' })).toBeInTheDocument();
  });

  it('never shows the back end’s own blocker text, and maps each blocker to the step it belongs to', async () => {
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
      'Data sharing, data protection and clinical safety references recorded',
      'System, referral system and coordination team names set',
      'Area districts set',
      'Network agreement accepted',
      'Host set',
      'Something nobody has thought of',
    ];
    await open({ ...VIEW_DETAIL_PROVISIONING, activation: { ready: false, blockers } });
    const text = document.body.textContent ?? '';
    for (const blocker of blockers) expect(text).not.toContain(blocker);
    expect(text).not.toContain('Number tested');
    const missing = within(step('Go live')).getByRole('list', { name: 'Still to do' }).textContent ?? '';
    expect(missing).toContain('Their administrator has not accepted the network agreement yet. (Go live, step 8)');
    expect(missing).toContain('Overwatch cannot send email for this organisation yet. Tell the Overwatch team. (Invite their administrator, step 3)');
    expect(missing).toContain('The time zone is not set. (Confirm the organisation, step 1)');
    expect(missing).toContain('Something else still has to be finished. Tell the Overwatch team. (Go live, step 8)');
    expect(missing).toContain('(Go live, step 8)');
    expect(within(step('Go live')).getAllByRole('listitem').length).toBeGreaterThan(8);
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

  it('says a live organisation is live, with no Go live button', async () => {
    await open(VIEW_DETAIL_ACTIVE);
    expect(within(step('Go live')).getByText(/This organisation is live since 22 Oct 2026/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Go live' })).not.toBeInTheDocument();
    expect(document.querySelector('[data-el="OP-NEXT-STEP"]')).not.toBeInTheDocument();
  });

  it('has no axe violations when ready', async () => {
    await open(VIEW_DETAIL_READY, CONSENTED);
    await within(step('Go live')).findByRole('button', { name: 'Go live' });
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});

describe('step 2: connect their sign-in', () => {
  it('confirms the Microsoft account the organisation named, with one button', async () => {
    const user = await open();
    await user.click(within(step('Connect their sign-in')).getByRole('button', { name: 'Confirm this is their Microsoft account' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ method: 'POST', path: '/api/bff/platform/tenants/trust-b/directory/verification', body: { directoryId: '11111111-1111-4111-8111-111111111111' } });
    expect(lastWrite()?.key).toBeTruthy();
  });

  it('says the connection in words once confirmed, and offers no button', async () => {
    await open(VIEW_DETAIL_READY, CONSENTED);
    const card = step('Connect their sign-in');
    expect(within(card).getByText('Connected to Sample Area B’s Microsoft accounts.')).toBeInTheDocument();
    expect(within(card).queryByRole('button', { name: 'Confirm this is their Microsoft account' })).not.toBeInTheDocument();
  });

  it('says nothing is connected when no account is named, and offers no button', async () => {
    await open({ ...VIEW_DETAIL_PROVISIONING, directoryId: null, bindings: [], roleMappings: [] });
    const card = step('Connect their sign-in');
    expect(within(card).getByText('No Microsoft account is connected yet.', { selector: 'p' })).toBeInTheDocument();
    expect(within(card).queryByRole('button', { name: 'Confirm this is their Microsoft account' })).not.toBeInTheDocument();
  });

  it('looks up their Microsoft account from the domain as a card, and says whether it is the one named, and saves nothing', async () => {
    server.use(http.get('/api/bff/platform/directory-lookup', () => HttpResponse.json({ domain: 'example-trust.test', directoryId: '11111111-1111-4111-8111-111111111111' })));
    const user = await open();
    const card = step('Connect their sign-in');
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
    const user = await open();
    const card = step('Connect their sign-in');
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
  const card = () => step('Invite their administrator');

  it('explains in plain words what approval allows', async () => {
    await open();
    expect(card()).toHaveTextContent('Approving lets Overwatch make teams there, add people to them and find people by email address. It does not let Overwatch read anyone’s email or files.');
  });

  it('says no link has been sent, and emails their administrator on a valid address', async () => {
    const user = await open();
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
    const user = await open();
    await user.type(await within(card()).findByLabelText('Their administrator’s work email'), 'not an address');
    await user.click(within(card()).getByRole('button', { name: 'Send the approval link to their administrator' }));
    expect(await within(card()).findByText('Enter the administrator’s work email address, for example name@organisation.nhs.uk.', { selector: 'p' })).toBeInTheDocument();
    expect(seenOperatorWrites).toEqual([]);
  });

  it('says it is waiting for approval, with the masked address, and offers to send the link again', async () => {
    await open(VIEW_DETAIL_PROVISIONING, invitation('pending', { reason: 'Overwatch is not installed in your directory yet.' }));
    expect(await within(card()).findByText(/Waiting for approval\. The link went to j\*\*\*@example-trust\.test and works until/)).toBeInTheDocument();
    expect(within(card()).getByRole('button', { name: 'Send the link again' })).toBeInTheDocument();
    expect(headline('Invite their administrator')).not.toContain('is not installed');
    expect(detailsOf('Invite their administrator').getByText('Overwatch is not installed in your directory yet.')).toBeInTheDocument();
  });

  it('says the link has expired, and offers to send it again', async () => {
    await open(VIEW_DETAIL_PROVISIONING, invitation('expired'));
    expect(await within(card()).findByText('The approval link has expired. Send a new one.')).toBeInTheDocument();
    expect(within(card()).getByRole('button', { name: 'Send the link again' })).toBeInTheDocument();
  });

  it('says it is approved, and offers no form', async () => {
    await open(VIEW_DETAIL_PROVISIONING, invitation('consented', { consentedAt: '2026-11-02T10:00:00Z' }));
    expect(await within(card()).findByText(/Approved on 2 Nov 2026/)).toBeInTheDocument();
    expect(within(card()).queryByRole('button', { name: /Send/ })).not.toBeInTheDocument();
  });

  it('does not offer the form until their sign-in is connected', async () => {
    await open({ ...VIEW_DETAIL_PROVISIONING, bindings: [] });
    expect(await within(card()).findByText('Connect their sign-in first (step 2). The approval link is for their Microsoft account.')).toBeInTheDocument();
    expect(within(card()).queryByRole('button', { name: /Send/ })).not.toBeInTheDocument();
  });

  it('says it could not be sent, without the address, when the back end refuses', async () => {
    server.use(http.post('/api/bff/platform/tenants/:id/admin-consent-invitation', () => HttpResponse.json({ code: 'conflict' }, { status: 409 })));
    const user = await open();
    await user.type(await within(card()).findByLabelText('Their administrator’s work email'), 'jane.admin@example-trust.test');
    await user.click(within(card()).getByRole('button', { name: 'Send the approval link to their administrator' }));
    expect(await within(card()).findByRole('alert')).toHaveTextContent('The link could not be sent. Connect their sign-in first (step 2), and check that Overwatch can send email.');
  });
});

describe('step 4: their administrators’ team', () => {
  const card = () => step('Set up their administrators’ team');
  const withAdmin = ready();

  it('offers nothing until their administrator has approved', async () => {
    await open();
    expect(await within(card()).findByText('You can create their administrators’ team once their administrator has approved Overwatch (step 3).')).toBeInTheDocument();
    expect(within(card()).queryByRole('button')).not.toBeInTheDocument();
  });

  it('explains that this team is the only route to administrator rights', async () => {
    await open();
    expect(card()).toHaveTextContent('The administrators’ team is the only way anyone gets administrator rights in Overwatch.');
  });

  it('creates the team once, sending no roles and no name, and lists what was made under Details', async () => {
    const user = await open(VIEW_DETAIL_PROVISIONING, CONSENTED);
    await user.click(await within(card()).findByRole('button', { name: 'Create their administrators’ team' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ method: 'POST', path: '/api/bff/platform/tenants/trust-b/entra-groups', csrf: OPERATOR_SAMPLE_CSRF, body: { roles: [] } });
    expect(lastWrite()?.key).toBeTruthy();
    expect(await within(card()).findByText('Their administrators’ team is in place.')).toBeInTheDocument();
    expect(detailsOf('Set up their administrators’ team').getByRole('row', { name: /Administrators RXX01_overwatch_tenant-admin Made now/ })).toBeInTheDocument();
    expect(headline('Set up their administrators’ team')).not.toContain('RXX01_overwatch');
  });

  it('says the directory could not be reached, in words', async () => {
    server.use(http.post('/api/bff/platform/tenants/:id/entra-groups', () => HttpResponse.json({ code: 'transient' }, { status: 503 })));
    const user = await open(VIEW_DETAIL_PROVISIONING, CONSENTED);
    await user.click(await within(card()).findByRole('button', { name: 'Create their administrators’ team' }));
    expect(await within(card()).findByRole('alert')).toHaveTextContent('Their Microsoft account could not be reached. Try again in a minute.');
  });

  it('once the team exists, says so and adds the first administrator by email, never showing or keeping the address', async () => {
    const user = await open(withAdmin, CONSENTED);
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
    const user = await open(withAdmin, CONSENTED);
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
    await open();
    expect(screen.queryByRole('region', { name: 'First administrator' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Send invitation' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Mobile number')).not.toBeInTheDocument();
  });

  it('has no axe violations once approved', async () => {
    await open(withAdmin, CONSENTED);
    await within(card()).findByRole('button', { name: 'Add the first administrator by email' });
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});

describe('step 5: who can do what', () => {
  const card = () => step('Who can do what');

  it('lists the six teams in plain words with what each can do, each added to Overwatch only when it exists', async () => {
    await open();
    const list = within(card()).getAllByRole('listitem');
    expect(list.map((li) => li.querySelector('strong')?.textContent)).toEqual(['Advisors', 'Shift leads', 'Clinical leads', 'Planning', 'Audit', 'Criteria owners']);
    expect(within(list[1]!).getByText('Added to Overwatch')).toBeInTheDocument();
    expect(within(list[0]!).getByText('Not added yet')).toBeInTheDocument();
    expect(list[4]).toHaveTextContent('They cannot change anything.');
  });

  it('says the administrators’ team is the only route to administrator rights', async () => {
    await open();
    expect(card()).toHaveTextContent('The administrators’ team above is the only route to administrator rights: none of these teams gives them.');
  });

  it('offers nothing to tick until their administrator has approved', async () => {
    await open();
    expect(await within(card()).findByText('Teams can be added once their administrator has approved Overwatch (step 3).')).toBeInTheDocument();
    expect(within(card()).queryByRole('checkbox')).not.toBeInTheDocument();
    expect(within(card()).queryByRole('button', { name: 'Add the ticked teams' })).not.toBeInTheDocument();
  });

  it('adds the teams that were ticked, sending only roles (no name, no group id), and says so', async () => {
    const user = await open(VIEW_DETAIL_PROVISIONING, CONSENTED);
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
    const user = await open(VIEW_DETAIL_PROVISIONING, CONSENTED);
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
    const user = await open(VIEW_DETAIL_PROVISIONING, CONSENTED);
    await user.click(await within(card()).findByRole('checkbox', { name: 'Planning' }));
    await user.click(within(card()).getByRole('button', { name: 'Add the ticked teams' }));
    expect(await within(card()).findByRole('alert')).toHaveTextContent('A team already gives a different role. Nothing was changed.');
  });
});

describe('step 6: how people reach them', () => {
  const card = () => step('How people reach them');

  it('sets the web address', async () => {
    const user = await open();
    await user.type(within(card()).getByLabelText('Web address'), 'tenant-b.example.test');
    await user.click(within(card()).getByRole('button', { name: 'Save web address' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ method: 'PUT', path: '/api/bff/platform/tenants/trust-b/host', csrf: OPERATOR_SAMPLE_CSRF, body: { host: 'tenant-b.example.test' } });
    expect(lastWrite()?.key).toBeTruthy();
    expect(await within(card()).findByText('Web address saved.')).toBeInTheDocument();
  });

  it('says the web address in words once set', async () => {
    await open(VIEW_DETAIL_READY, CONSENTED);
    expect(within(card()).getByText('Their web address is tenant-b.example.test.')).toBeInTheDocument();
  });

  it('records a text number in international form with the sender name, and refuses one that is not', async () => {
    const user = await open();
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

  it('marks a text number tested', async () => {
    const user = await open();
    await user.click(within(card()).getByRole('button', { name: 'Mark +441632960002 as tested' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ path: '/api/bff/platform/tenants/trust-b/numbers/tested', body: { e164: '+441632960002' } });
  });

  it('says a web address or number another organisation holds could not be saved, on a 409', async () => {
    server.use(http.put('/api/bff/platform/tenants/:id/host', () => HttpResponse.json({ code: 'conflict' }, { status: 409 })));
    const user = await open();
    await user.type(within(card()).getByLabelText('Web address'), 'taken.example.test');
    await user.click(within(card()).getByRole('button', { name: 'Save web address' }));
    expect(await within(card()).findByRole('alert')).toHaveTextContent('That web address is used by another organisation.');
  });

  it('says a write could not be made, and keeps what was typed', async () => {
    server.use(http.put('/api/bff/platform/tenants/:id/host', () => HttpResponse.json({}, { status: 503 })));
    const user = await open();
    await user.type(within(card()).getByLabelText('Web address'), 'tenant-b.example.test');
    await user.click(within(card()).getByRole('button', { name: 'Save web address' }));
    expect(await within(card()).findByRole('alert')).toHaveTextContent('The web address could not be saved. Try again.');
    expect(within(card()).getByLabelText('Web address')).toHaveValue('tenant-b.example.test');
  });
});

describe('step 7: agreements', () => {
  it('records the references that were filled in and needs at least one', async () => {
    const user = await open();
    const card = step('Agreements');
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
    const field = () => within(dialog).getByLabelText('Type the organisation id to confirm (shown under Details in step 1)');
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
