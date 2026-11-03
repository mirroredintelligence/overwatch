import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { VIEW_DETAIL_PROVISIONING } from '@/test/fixtures/operator';
import { resetOperatorWrites, seenOperatorWrites } from '@/test/msw/handlers/operator';
import { server } from '@/test/msw/server';
import { TenantDetail } from '../TenantDetail';

// Step 3 of an organisation's page (TEN-083), moved out of TenantDetail.test.tsx with the step's own file.

beforeEach(() => resetOperatorWrites());

const serveConsent = (body: unknown) => server.use(http.get('/api/bff/platform/tenants/:id/admin-consent', () => HttpResponse.json(body as Record<string, unknown>)));
function serve(detail: unknown) {
  server.use(http.get('/api/bff/platform/tenants/:id', () => HttpResponse.json(detail as Record<string, unknown>)));
}
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
