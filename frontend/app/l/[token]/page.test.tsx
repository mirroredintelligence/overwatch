import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { runAxe } from '@/test/a11y';
import { LINK, TENANT_HOST } from '@/test/fixtures/links';
import { resetLinkRequests, seenBackendRequests, seenBffPosts } from '@/test/msw/handlers/links';
import { server } from '@/test/msw/server';
import { http, HttpResponse } from 'msw';
import { BACKEND_ROOT } from '@/test/fixtures/links';
import LinkPage, { dynamic, metadata } from './page';

const { redirect } = vi.hoisted(() => ({
  redirect: vi.fn((to: string) => {
    throw Object.assign(new Error('NEXT_REDIRECT'), { digest: `NEXT_REDIRECT;${to}` });
  }),
}));

vi.mock('next/navigation', () => ({ redirect, useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));
vi.mock('next/headers', () => ({
  headers: async () => new Headers({ host: TENANT_HOST }),
}));

async function open(token: string) {
  const element = await LinkPage({ params: Promise.resolve({ token }) });
  return render(element as React.ReactElement);
}

beforeEach(() => {
  resetLinkRequests();
  redirect.mockClear();
});

describe('the link page', () => {
  it('renders the open link with the figure, its time and the question, and changes nothing', async () => {
    const { container } = await open(LINK.recorded);
    expect(screen.getByRole('heading', { level: 1, name: 'UCR West' })).toBeInTheDocument();
    expect(screen.getByText('We have 3 referrals in the next 2 hrs, as of 08:15. Still right?')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Yes, still 3' })).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('makes no POST when it renders, to the back end or the BFF', async () => {
    await open(LINK.recorded);
    expect(seenBffPosts).toHaveLength(0);
    expect(seenBackendRequests.filter((r) => r.method === 'POST')).toHaveLength(0);
  });

  it('reads the back end with the host the page was asked for, so the tenant is that host', async () => {
    await open(LINK.recorded);
    expect(seenBackendRequests.find((r) => r.method === 'GET')?.host).toBe(TENANT_HOST);
  });

  it('shows the expired message for an expired link, without a figure', async () => {
    const { container } = await open(LINK.expired);
    expect(screen.getByRole('heading', { level: 1, name: 'This link has expired' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Send me a new link' })).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('shows the same expired message for a used link as for an expired one', async () => {
    await open(LINK.used);
    expect(screen.getByRole('heading', { level: 1, name: 'This link has expired' })).toBeInTheDocument();
    expect(screen.queryByText(/used/i)).toBeNull();
  });

  it('says the link could not be loaded, and does not say it expired, when the back end is down', async () => {
    await open(LINK.down);
    expect(screen.getByText('We could not load this link. Try again in a few minutes.')).toBeInTheDocument();
    expect(screen.queryByText('This link has expired')).toBeNull();
  });

  it('sends a booking link to /l/[token]/booking', async () => {
    await expect(open(LINK.booking)).rejects.toThrow('NEXT_REDIRECT');
    expect(redirect).toHaveBeenCalledWith(`/l/${LINK.booking}/booking`);
  });

  it('treats a token that cannot be a link as expired, without calling the back end', async () => {
    await open('not/a/link');
    expect(screen.getByRole('heading', { level: 1, name: 'This link has expired' })).toBeInTheDocument();
    expect(seenBackendRequests).toHaveLength(0);
  });

  it('asks the browser not to send the link address as a referrer, and never caches the page', () => {
    expect(metadata).toMatchObject({ referrer: 'no-referrer', robots: { index: false, follow: false } });
    expect(dynamic).toBe('force-dynamic');
  });

  it('shows the unavailable message when the back end answers with an error the page does not know', async () => {
    server.use(http.get(`${BACKEND_ROOT}/links/:token`, () => HttpResponse.json({}, { status: 500 })));
    await open(LINK.recorded);
    expect(screen.getByText('We could not load this link. Try again in a few minutes.')).toBeInTheDocument();
  });
});
