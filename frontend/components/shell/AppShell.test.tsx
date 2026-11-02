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
  it('has the logo, the role, the organisation, the role navigation, Help and Sign out', () => {
    path.current = '/lead';
    page('lead', { organisation: 'Dorset system' });
    const header = screen.getByRole('banner');
    expect(within(header).getByRole('link', { name: 'Overwatch home' })).toHaveAttribute('href', '/lead');
    expect(within(header).getByRole('img', { name: 'Overwatch' })).toBeInTheDocument();
    expect(within(header).getByText('Shift lead')).toBeInTheDocument();
    expect(within(header).getByText('Dorset system')).toBeInTheDocument();
    const nav = within(header).getByRole('navigation', { name: 'Main' });
    expect(within(nav).getAllByRole('link').map((a) => a.textContent)).toEqual([
      'Overview',
      'Phones and services',
      'Set-up progress',
      'Registrations',
      'Audit replay',
    ]);
    expect(within(header).getByRole('link', { name: 'Help' })).toHaveAttribute('href', '/help');
    expect(within(header).getByRole('button', { name: 'Sign out' })).toBeInTheDocument();
  });

  it('marks the current page in the markup, only one', () => {
    path.current = '/lead/phones/move';
    page('lead');
    const current = screen.getAllByRole('link', { current: 'page' });
    expect(current).toHaveLength(1);
    expect(current[0]).toHaveTextContent('Phones and services');
  });

  it('adds no main landmark and no heading of its own, and holds the page', () => {
    page('advisor');
    expect(screen.getAllByRole('main')).toHaveLength(1);
    expect(screen.getAllByRole('heading')).toHaveLength(1);
    expect(screen.getByRole('heading', { level: 1, name: 'The page' })).toBeInTheDocument();
  });

  it('is the logo and Help only when nobody is signed in', () => {
    page(null);
    const header = screen.getByRole('banner');
    expect(within(header).getByRole('link', { name: 'Overwatch home' })).toHaveAttribute('href', '/');
    expect(within(header).getByRole('link', { name: 'Help' })).toBeInTheDocument();
    expect(within(header).queryByRole('navigation')).toBeNull();
    expect(within(header).queryByRole('button', { name: 'Sign out' })).toBeNull();
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
    const header = screen.getByRole('banner');
    expect(within(header).getByText('Clinical advisor', { selector: 'summary span' })).toBeInTheDocument();
    const menu = within(header).getByRole('form', { name: 'Sign in as another role', hidden: true });
    expect(within(menu).getAllByRole('button', { hidden: true }).map((b) => b.textContent)).toEqual(['Shift lead', 'Clinical advisor', 'Audit']);
    // The navigation, Help and Sign out are still there.
    expect(within(header).getByRole('navigation', { name: 'Main' })).toBeInTheDocument();
    expect(within(header).getByRole('button', { name: 'Sign out' })).toBeInTheDocument();
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
