import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';

const path = vi.hoisted(() => ({ current: '/lead' }));
vi.mock('next/navigation', () => ({ usePathname: () => path.current }));

import { AppShell } from './AppShell';

function page(role: Parameters<typeof AppShell>[0]['role'], extra: Partial<Parameters<typeof AppShell>[0]> = {}) {
  return render(
    <AppShell role={role} {...extra}>
      <main>
        <h1>The page</h1>
      </main>
    </AppShell>,
  );
}

describe('AppShell', () => {
  it('has the mark, the role, the organisation, the role navigation, Help and Sign out', () => {
    path.current = '/lead';
    page('lead', { organisation: 'Dorset system' });
    const top = screen.getByRole('banner');
    expect(screen.getByRole('link', { name: 'Overwatch home' })).toHaveAttribute('href', '/lead');
    expect(within(top).getByText('Shift lead')).toBeInTheDocument();
    expect(within(top).getByText('Dorset system')).toBeInTheDocument();
    const nav = screen.getByRole('navigation', { name: 'Main' });
    expect(within(nav).getAllByRole('link').map((a) => a.textContent)).toEqual([
      'Overview',
      'Phones and services',
      'Set-up progress',
      'Registrations',
      'Audit replay',
    ]);
    expect(screen.getByRole('link', { name: 'Help' })).toHaveAttribute('href', '/help');
    expect(within(top).getByRole('button', { name: 'Sign out' })).toBeInTheDocument();
  });

  it('marks the current page in the markup, only one, and names it in the top bar', () => {
    path.current = '/lead/phones/move';
    page('lead');
    const current = screen.getAllByRole('link', { current: 'page' });
    expect(current).toHaveLength(1);
    expect(current[0]).toHaveTextContent('Phones and services');
    expect(within(screen.getByRole('banner')).getByText('Phones and services')).toBeInTheDocument();
  });

  it('marks the role’s home only on its own page', () => {
    path.current = '/lead/audit';
    page('lead');
    expect(screen.getAllByRole('link', { current: 'page' }).map((a) => a.textContent)).toEqual(['Audit replay']);
  });

  it('adds no main landmark and no heading of its own, and holds the page', () => {
    page('advisor');
    expect(screen.getAllByRole('main')).toHaveLength(1);
    expect(screen.getAllByRole('heading')).toHaveLength(1);
    expect(screen.getByRole('heading', { level: 1, name: 'The page' })).toBeInTheDocument();
  });

  it('is the mark and Help only when nobody is signed in', () => {
    page(null);
    expect(screen.getByRole('link', { name: 'Overwatch home' })).toHaveAttribute('href', '/');
    expect(screen.getByRole('link', { name: 'Help' })).toBeInTheDocument();
    expect(screen.queryByRole('navigation')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Sign out' })).toBeNull();
  });

  it('has no navigation for a role with no staff pages, but still signs out', () => {
    page('wall');
    expect(screen.queryByRole('navigation')).toBeNull();
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeInTheDocument();
  });

  it('signs out through the sign-out function it is given', async () => {
    const signOut = vi.fn(async () => ({ signedOut: true, failed: [], navigated: true }));
    page('exec', { signOut });
    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }));
    expect(signOut).toHaveBeenCalledTimes(1);
  });

  it('shows the role as a chip, in the header’s own words, when the person holds more than one', () => {
    path.current = '/clinical';
    page('clinical', { roles: ['lead', 'clinical', 'audit'] });
    const top = screen.getByRole('banner');
    expect(within(top).getByText('Clinical advisor', { selector: 'summary span' })).toBeInTheDocument();
    const menu = within(top).getByRole('form', { name: 'Sign in as another role', hidden: true });
    expect(within(menu).getAllByRole('button', { hidden: true }).map((b) => b.textContent)).toEqual(['Shift lead', 'Clinical advisor', 'Audit']);
    // The navigation, Help and Sign out are still there.
    expect(screen.getByRole('navigation', { name: 'Main' })).toBeInTheDocument();
    expect(within(top).getByRole('button', { name: 'Sign out' })).toBeInTheDocument();
  });

  it('keeps the plain role words with one role, with none known, or with a list that does not hold the role', () => {
    page('lead', { roles: ['lead'] });
    expect(document.querySelector('details')).toBeNull();
    expect(screen.getByText('Shift lead')).toBeInTheDocument();
    document.body.innerHTML = '';
    page('lead');
    expect(document.querySelector('details')).toBeNull();
    document.body.innerHTML = '';
    page('lead', { roles: ['advisor', 'audit'] });
    expect(document.querySelector('details')).toBeNull();
  });

  it('passes the accessibility checks signed in and signed out', async () => {
    path.current = '/planning';
    const signedIn = page('exec', { organisation: 'Dorset system' });
    expect(await runAxe(signedIn.container)).toHaveNoViolations();
    signedIn.unmount();
    const signedOut = page(null);
    expect(await runAxe(signedOut.container)).toHaveNoViolations();
  });
});
