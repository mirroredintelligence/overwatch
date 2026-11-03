import { render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetReporterRequests, seenBffRequests } from '@/test/msw/handlers/reporter';
import { server } from '@/test/msw/server';
import { InvitationExpired, InvitationLoader } from './InvitationLoader';

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), replace }) }));

beforeEach(() => {
  replace.mockClear();
  resetReporterRequests();
});

const EXPIRED_TEXT = 'Invitations work for 48 hours. Ask your shift lead to send you a new one.';

describe('InvitationLoader (/i/[token])', () => {
  it('redirects a valid invitation to /setup?invite=<token>', async () => {
    render(<InvitationLoader token="tok" />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/setup?invite=tok'));
  });

  it('says it is checking while it looks the invitation up, as a shimmer with a spoken label', () => {
    render(<InvitationLoader token="tok" />);
    const status = screen.getByRole('status');
    expect(status).toHaveTextContent('Checking your invitation');
    expect(status).toHaveAttribute('aria-busy', 'true');
  });

  it('shows the Expired state for an expired invitation and does not redirect', async () => {
    server.use(
      http.get('/api/bff/invitations/:token', () => HttpResponse.json({ state: 'expired' }, { status: 410 })),
    );
    const { container } = render(<InvitationLoader token="tok" />);
    expect(await screen.findByRole('heading', { level: 1, name: 'This invitation has expired' })).toBeInTheDocument();
    expect(screen.getByText(EXPIRED_TEXT)).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
    expect(await runAxe(container)).toHaveNoViolations();
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

describe('InvitationExpired (a token that cannot be an invitation)', () => {
  it('is the Expired state, with a heading, a plain instruction and no request made', async () => {
    const { container } = render(<InvitationExpired />);
    expect(screen.getByRole('heading', { level: 1, name: 'This invitation has expired' })).toBeInTheDocument();
    expect(screen.getByText(EXPIRED_TEXT)).toBeInTheDocument();
    expect(screen.getByRole('main')).toBeInTheDocument();
    expect(seenBffRequests).toHaveLength(0);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
