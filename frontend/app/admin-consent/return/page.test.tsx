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

  it('says it is approved only when the back end confirmed it', async () => {
    confirmConsent.mockResolvedValue({ kind: 'consented', organisation: 'Sample Organisation' });
    await show({ state: STATE, admin_consent: 'True' });
    expect(screen.getByRole('heading', { level: 1, name: 'Overwatch is approved' })).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Sample Organisation can now go ahead with Overwatch.');
  });

  it('says not approved yet, with the reason, even when the redirect said True', async () => {
    confirmConsent.mockResolvedValue({ kind: 'pending', reason: 'Overwatch is not installed in your directory yet.', organisation: null });
    await show({ state: STATE, admin_consent: 'True' });
    expect(screen.getByRole('heading', { level: 1, name: 'Not approved yet' })).toBeInTheDocument();
    expect(screen.getByText('Overwatch is not installed in your directory yet.')).toBeInTheDocument();
    expect(screen.queryByText(/is approved/)).not.toBeInTheDocument();
  });

  it.each([
    [{ kind: 'invalid' }, 'This link is not valid'],
    [{ kind: 'unavailable' }, 'We could not check just now'],
    [{ kind: 'expired', reason: 'This invitation has expired.' }, 'This link can no longer be used'],
    [{ kind: 'revoked', reason: 'This invitation was replaced by a newer one.' }, 'This link can no longer be used'],
  ])('shows %j in words', async (outcome, heading) => {
    confirmConsent.mockResolvedValue(outcome);
    await show({ state: STATE });
    expect(screen.getByRole('heading', { level: 1, name: heading })).toBeInTheDocument();
  });

  it('ignores a state given twice, and has no axe violations and one main landmark', async () => {
    confirmConsent.mockResolvedValue({ kind: 'invalid' });
    const { container } = await show({ state: [STATE, STATE] });
    expect(confirmConsent).toHaveBeenCalledWith({ state: undefined, adminConsent: undefined, host: 'overwatch.example.test' });
    expect(screen.getAllByRole('main')).toHaveLength(1);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
