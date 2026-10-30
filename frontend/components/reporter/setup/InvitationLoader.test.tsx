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
      http.get('/api/bff/invitations/:token', () =>
        HttpResponse.json({ service: 'UCR West', role: 'reporter', maskedPhone: '07xxx xxx456', expiresAt: '2026-10-29T10:00:00Z', state: 'expired' }),
      ),
    );
    render(<InvitationLoader token="tok" />);
    expect(
      await screen.findByText('This invitation has expired. Ask the SPOA shift lead to send a new one.'),
    ).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });

  it('says the invitation could not be checked when the back end is not available', async () => {
    server.use(http.get('/api/bff/invitations/:token', () => HttpResponse.json({ code: 'not-built' }, { status: 503 })));
    render(<InvitationLoader token="tok" />);
    expect(await screen.findByText('We could not check this invitation. Try again shortly.')).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });
});
