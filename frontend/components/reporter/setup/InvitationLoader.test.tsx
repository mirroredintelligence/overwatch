import { render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { server } from '@/test/msw/server';
import { InvitationLoader } from './InvitationLoader';

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), replace }) }));

beforeEach(() => replace.mockClear());

describe('InvitationLoader (/i/[token])', () => {
  it('redirects a valid invitation to /setup?invite=<token>', async () => {
    render(<InvitationLoader token="tok" />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/setup?invite=tok'));
  });

  it('shows the expired text for an expired invitation and does not redirect', async () => {
    server.use(
      http.get('/api/bff/invitations/:token', () => HttpResponse.json({ state: 'expired' }, { status: 410 })),
    );
    render(<InvitationLoader token="tok" />);
    expect(
      await screen.findByText('This invitation has expired. Ask the shift lead to send a new one.'),
    ).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });

  it('says the invitation could not be checked for an answer that is not an invitation, and never calls it expired', async () => {
    server.use(http.get('/api/bff/invitations/:token', () => HttpResponse.json({ nothing: true })));
    render(<InvitationLoader token="tok" />);
    expect(await screen.findByText('We could not check this invitation. Try again shortly.')).toBeInTheDocument();
    expect(screen.queryByText(/has expired/)).toBeNull();
  });

  it('says the invitation could not be checked when the back end is not available', async () => {
    server.use(http.get('/api/bff/invitations/:token', () => HttpResponse.json({ code: 'unavailable' }, { status: 503 })));
    render(<InvitationLoader token="tok" />);
    expect(await screen.findByText('We could not check this invitation. Try again shortly.')).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });
});
