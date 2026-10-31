import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';

let path = '/admin';
vi.mock('next/navigation', () => ({ usePathname: () => path }));

import { AdminNav } from './AdminNav';
import { SignOutButton } from '@/components/session/SignOutButton';

// The administration's navigation (TEN-076): every page of the administration, the current one marked in the
// markup for a screen reader and by an underline for the eye, and the way to sign out.

beforeEach(() => {
  path = '/admin';
});

describe('AdminNav', () => {
  it('links to the overview and every page of the administration, in a navigation named for it', () => {
    render(<AdminNav />);
    const links = screen.getAllByRole('link').map((a) => [a.textContent, a.getAttribute('href')]);
    expect(links).toEqual([
      ['Overview', '/admin'],
      ['Settings and versions', '/admin/config'],
      ['Users and roles', '/admin/users'],
      ['Contacts', '/admin/contacts'],
      ['Email sender', '/admin/email'],
      ['Data retention', '/admin/retention'],
      ['Who has accessed your organisation', '/admin/access'],
      ['Support requests', '/admin/support'],
    ]);
    expect(screen.getByRole('navigation', { name: 'Administration' })).toBeInTheDocument();
  });

  it.each([
    ['/admin', 'Overview'],
    ['/admin/config', 'Settings and versions'],
    ['/admin/config/3', 'Settings and versions'],
    ['/admin/support', 'Support requests'],
  ])('marks %s as the current page: %s', (current, name) => {
    path = current;
    render(<AdminNav />);
    const marked = screen.getAllByRole('link').filter((a) => a.getAttribute('aria-current') === 'page');
    expect(marked.map((a) => a.textContent)).toEqual([name]);
  });

  it('has no axe violations', async () => {
    const { container } = render(<AdminNav />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});

describe('SignOutButton', () => {
  it('signs out with the function it is given and says nothing when it works', async () => {
    const signOut = vi.fn(async () => ({ signedOut: true }));
    render(<SignOutButton signOut={signOut} />);
    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }));
    expect(signOut).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('says it could not sign out, and offers to try again, when it fails', async () => {
    const signOut = vi.fn(async () => ({ signedOut: false }));
    render(<SignOutButton signOut={signOut} />);
    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not sign you out. Try again.');
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeEnabled();
  });
});
