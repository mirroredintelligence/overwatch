import { render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { LINK } from '@/test/fixtures/links';
import { resetLinkRequests, seenBackendRequests, seenBffPosts } from '@/test/msw/handlers/links';
import { server } from '@/test/msw/server';
import { LinkLoader } from './LinkLoader';

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), replace }) }));

beforeEach(() => {
  resetLinkRequests();
  replace.mockClear();
});

describe('LinkLoader', () => {
  it('shows the link’s figure and its question once it has read the link', async () => {
    const { container } = render(<LinkLoader token={LINK.recorded} />);
    expect(screen.getByRole('status')).toHaveTextContent('Opening your link');
    expect(await screen.findByRole('heading', { level: 1, name: 'UCR West' })).toBeInTheDocument();
    expect(screen.getByText('We have 3 referrals in the next 2 hrs, as of 08:15. Still right?')).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('makes no POST when the link is read, to the BFF or the back end', async () => {
    render(<LinkLoader token={LINK.recorded} />);
    await screen.findByRole('button', { name: 'Yes, still 3' });
    expect(seenBffPosts).toHaveLength(0);
    expect(seenBackendRequests.filter((r) => r.method === 'POST')).toHaveLength(0);
  });

  it('shows the expired message for an expired link, without a figure', async () => {
    const { container } = render(<LinkLoader token={LINK.expired} />);
    expect(await screen.findByRole('heading', { level: 1, name: 'This link has expired' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Send me a new link' })).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('shows the same expired message for a used link as for an expired one, word for word', async () => {
    const { container, unmount } = render(<LinkLoader token={LINK.expired} />);
    await screen.findByRole('heading', { level: 1, name: 'This link has expired' });
    const expired = container.textContent;
    unmount();
    const used = render(<LinkLoader token={LINK.used} />);
    await screen.findByRole('heading', { level: 1, name: 'This link has expired' });
    expect(used.container.textContent).toBe(expired);
  });

  it('says the link could not be loaded, and does not say it expired, when the back end is down', async () => {
    render(<LinkLoader token={LINK.down} />);
    expect(await screen.findByText('We could not load this link. Try again in a few minutes.')).toBeInTheDocument();
    expect(screen.queryByText('This link has expired')).toBeNull();
  });

  it('says the link could not be loaded when the BFF answers with an error the page does not know', async () => {
    server.use(http.get('/api/bff/links/:token', () => HttpResponse.json({}, { status: 500 })));
    render(<LinkLoader token={LINK.recorded} />);
    expect(await screen.findByText('We could not load this link. Try again in a few minutes.')).toBeInTheDocument();
  });

  it('says the link could not be loaded when the answer is not a link the page can read', async () => {
    server.use(http.get('/api/bff/links/:token', () => HttpResponse.json({ state: 'ok' }, { status: 200 })));
    render(<LinkLoader token={LINK.recorded} />);
    expect(await screen.findByText('We could not load this link. Try again in a few minutes.')).toBeInTheDocument();
  });

  it('sends a booking link on to /l/[token]/booking', async () => {
    render(<LinkLoader token={LINK.booking} />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith(`/l/${LINK.booking}/booking`));
  });

  it('says the link could not be loaded for a purpose this page does not serve', async () => {
    server.use(
      http.get('/api/bff/links/:token', () =>
        HttpResponse.json({
          state: 'ok',
          purpose: 'something-else',
          serviceName: 'UCR West',
          unitLabel: 'referrals in the next 2 hrs',
          recordedValue: 3,
          asOf: '2026-10-23T07:15:00Z',
          usualMin: 0,
          usualMax: 8,
          replyBy: '2026-10-23T09:30:00Z',
          nextDue: null,
          csrfToken: 'csrf-x',
        }),
      ),
    );
    render(<LinkLoader token={LINK.recorded} />);
    expect(await screen.findByText('We could not load this link. Try again in a few minutes.')).toBeInTheDocument();
  });
});
