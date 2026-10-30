import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import RegisterPage from './page';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

// Self-registration sign-in (W23). The invitation is read from ?invite= and handed to the form; it
// is never shown. ?saved=1 comes back from "Save and come back later" on the start page.

type Query = Record<string, string | string[] | undefined>;

async function open(query: Query = {}) {
  return render(await RegisterPage({ searchParams: Promise.resolve(query) }));
}

describe('register page', () => {
  it('shows the heading and the sign-in form', async () => {
    await open({ invite: 'InviteTokenSampleValue1' });
    expect(screen.getByRole('heading', { level: 1, name: 'Register your service' })).toBeInTheDocument();
    expect(screen.getByLabelText('Mobile number')).toBeInTheDocument();
  });

  it('shows the saved-draft note only when it comes back from Save and come back later', async () => {
    const note = 'Your draft is saved. Use your invitation link to come back.';
    const { unmount } = await open({ saved: '1' });
    expect(screen.getByText(note)).toBeInTheDocument();
    unmount();
    await open({});
    expect(screen.queryByText(note)).not.toBeInTheDocument();
  });

  it('never renders the invitation token', async () => {
    const { container } = await open({ invite: 'InviteTokenSampleValue1' });
    expect(container.innerHTML).not.toContain('InviteTokenSampleValue1');
  });

  it('has no axe violations', async () => {
    const { container } = await open({});
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
