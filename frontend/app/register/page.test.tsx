import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { withApplicantHandlers } from '@/test/msw/applicant';
import RegisterPage from './page';

withApplicantHandlers();

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
    // The invitation decides whose number the code goes to: the page reads the link, then offers to send the code.
    expect(await screen.findByRole('button', { name: 'Send code' })).toBeInTheDocument();
    expect(screen.queryByLabelText('Mobile number')).toBeNull();
  });

  it('names the service the invitation is for and says an invitation is needed', async () => {
    await open({ invite: 'InviteTokenSampleValue1' });
    expect(await screen.findByText(/^Invited for /)).toBeInTheDocument();
    expect(screen.getByText('You need an invitation from your shift lead to register. Check your texts or email for the link.')).toBeInTheDocument();
  });

  it('is one page with a single h1 and the sign-in in the main region', async () => {
    await open({ invite: 'InviteTokenSampleValue1' });
    await screen.findByRole('button', { name: 'Send code' });
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
    expect(within(screen.getByRole('main')).getByRole('button', { name: 'Send code' })).toBeInTheDocument();
  });

  it('with no usable invitation says so under the heading and offers no code', async () => {
    await open({ invite: 'short' });
    expect(screen.getByText('We could not find an invitation for this link. Ask the shift lead to check your invitation.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Send code' })).toBeNull();
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
