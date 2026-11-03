import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';

const confirmConsent = vi.fn();
vi.mock('@/lib/adminConsent/confirm', () => ({ confirmConsent: (...args: unknown[]) => confirmConsent(...args) }));
vi.mock('next/headers', () => ({ headers: async () => new Headers({ host: 'overwatch.example.test' }) }));

import AdminConsentReturnPage from './page';

const STATE = `new-org.${'A'.repeat(43)}`;

async function show(query: Record<string, string | string[] | undefined>) {
  return render(await AdminConsentReturnPage({ searchParams: Promise.resolve(query) }));
}

beforeEach(() => confirmConsent.mockReset());

describe('the return page of the admin consent', () => {
  it('asks the back end with the state and the redirect’s word, and the host it was reached on, and reads no tenant', async () => {
    confirmConsent.mockResolvedValue({ kind: 'consented', organisation: 'Sample Organisation' });
    await show({ state: STATE, admin_consent: 'True', tenant: 'someone-elses-directory' });

    expect(confirmConsent).toHaveBeenCalledWith({ state: STATE, adminConsent: 'True', host: 'overwatch.example.test' });
    expect(JSON.stringify(confirmConsent.mock.calls)).not.toContain('someone-elses-directory');
  });

  it('shows the product name as a brand line above the outcome', async () => {
    confirmConsent.mockResolvedValue({ kind: 'invalid' });
    await show({ state: STATE });
    expect(screen.getByText('Overwatch', { selector: 'p' })).toBeInTheDocument();
  });

  it('says it is approved only when the back end confirmed it, in the large approved card', async () => {
    confirmConsent.mockResolvedValue({ kind: 'consented', organisation: 'Sample Organisation' });
    const { container } = await show({ state: STATE, admin_consent: 'True' });
    expect(screen.getByRole('heading', { level: 1, name: 'Overwatch is approved' })).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Sample Organisation can now go ahead with Overwatch. You can close this page.');
    expect(screen.getByText(/Enterprise applications/)).toBeInTheDocument();
    expect(container.querySelector('[data-outcome="consented"]')).not.toBeNull();
  });

  it('names no organisation before the back end confirms, and falls back to a plain word', async () => {
    confirmConsent.mockResolvedValue({ kind: 'consented', organisation: null });
    await show({ state: STATE, admin_consent: 'True' });
    expect(screen.getByRole('status')).toHaveTextContent('Your organisation can now go ahead with Overwatch.');
  });

  it('gives no check-again action once approved', async () => {
    confirmConsent.mockResolvedValue({ kind: 'consented', organisation: 'Sample Organisation' });
    await show({ state: STATE, admin_consent: 'True' });
    expect(screen.queryByRole('button', { name: 'Check again' })).not.toBeInTheDocument();
  });

  it('says not approved yet, in words, even when the redirect said True, and never says approved', async () => {
    confirmConsent.mockResolvedValue({ kind: 'pending', reason: 'Overwatch is not installed in your directory yet.', organisation: null });
    await show({ state: STATE, admin_consent: 'True' });
    expect(screen.getByRole('heading', { level: 1, name: 'Not approved yet' })).toBeInTheDocument();
    expect(screen.getByText(/We could not see Overwatch in your directory yet/)).toBeInTheDocument();
    expect(screen.getByText(/Approvals can take a minute to appear/)).toBeInTheDocument();
    expect(screen.queryByText(/is approved/)).not.toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('offers Check again on the pending state, as a form that re-asks the same state, with a 52px button', async () => {
    confirmConsent.mockResolvedValue({ kind: 'pending', reason: 'x', organisation: null });
    await show({ state: STATE, admin_consent: 'True' });
    const button = screen.getByRole('button', { name: 'Check again' });
    const form = button.closest('form');
    expect(form).not.toBeNull();
    expect(form).toHaveAttribute('action', '/admin-consent/return');
    expect(form).toHaveAttribute('method', 'get');
    expect(form?.querySelector('input[name="state"]')).toHaveValue(STATE);
    expect(form?.querySelector('input[name="admin_consent"]')).toHaveValue('True');
  });

  it.each([
    [{ kind: 'invalid' }, 'This link is not valid', 'Ask the person who set up Overwatch to send a new invitation.'],
    [{ kind: 'unavailable' }, 'We could not check just now', 'Nothing has been changed. Open the link in the email again in a few minutes.'],
    [{ kind: 'expired', reason: 'This invitation has expired.' }, 'This link can no longer be used', 'It has expired or been withdrawn. Ask the person who set up Overwatch to send a new invitation.'],
    [{ kind: 'revoked', reason: 'This invitation was replaced by a newer one.' }, 'This link can no longer be used', 'It has expired or been withdrawn. Ask the person who set up Overwatch to send a new invitation.'],
  ])('shows %j in words, with the board’s sentence', async (outcome, heading, sentence) => {
    confirmConsent.mockResolvedValue(outcome);
    await show({ state: STATE });
    expect(screen.getByRole('heading', { level: 1, name: heading })).toBeInTheDocument();
    expect(screen.getByText(sentence)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Check again' })).not.toBeInTheDocument();
  });

  it('ignores a state given twice, has no check-again form without a state, and has no axe violations and one main landmark', async () => {
    confirmConsent.mockResolvedValue({ kind: 'invalid' });
    const { container } = await show({ state: [STATE, STATE] });
    expect(confirmConsent).toHaveBeenCalledWith({ state: undefined, adminConsent: undefined, host: 'overwatch.example.test' });
    expect(screen.getAllByRole('main')).toHaveLength(1);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
