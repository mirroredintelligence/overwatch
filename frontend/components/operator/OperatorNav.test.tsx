import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';

let path = '/operator';
vi.mock('next/navigation', () => ({ usePathname: () => path }));

import { OperatorFooter } from './OperatorFooter';
import { OperatorNav } from './OperatorNav';

// The console's navigation (TEN-083): the pages of the role, the current one marked, the role said in words
// and a sign-out of the console's own.

describe('OperatorNav', () => {
  it('shows the operator the tenants and the audit chain, and says the role', () => {
    path = '/operator';
    render(<OperatorNav role="platform-operator" />);
    expect(screen.getByRole('navigation', { name: 'Platform console' })).toBeInTheDocument();
    expect(screen.getAllByRole('link').map((a) => [a.textContent, a.getAttribute('href')])).toEqual([
      ['Tenants', '/operator'],
      ['Audit chain', '/operator/audit'],
    ]);
    expect(screen.getByText('Signed in as platform operator')).toBeInTheDocument();
  });

  it('shows a support person the support requests and the tenants, and no audit chain', () => {
    path = '/operator/support/new';
    render(<OperatorNav role="support" />);
    expect(screen.getAllByRole('link').map((a) => [a.textContent, a.getAttribute('href')])).toEqual([
      ['Support requests', '/operator/support'],
      ['Tenants', '/operator'],
    ]);
    expect(screen.getByText('Signed in as support')).toBeInTheDocument();
    expect(screen.getAllByRole('link').filter((a) => a.getAttribute('aria-current') === 'page').map((a) => a.textContent)).toEqual(['Support requests']);
  });

  it('marks only the current page, and the tenants for a tenant’s own page', () => {
    path = '/operator/tenants/trust-b';
    render(<OperatorNav role="platform-operator" />);
    expect(screen.getAllByRole('link').filter((a) => a.getAttribute('aria-current') === 'page').map((a) => a.textContent)).toEqual(['Tenants']);
  });

  it('has no axe violations', async () => {
    path = '/operator';
    const { container } = render(<OperatorNav role="platform-operator" />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});

describe('OperatorFooter', () => {
  it('signs out with the console’s own sign-out', async () => {
    const signOut = vi.fn(async () => ({ signedOut: true }));
    render(<OperatorFooter signOut={signOut} />);
    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }));
    expect(signOut).toHaveBeenCalledTimes(1);
  });
});
