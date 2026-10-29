import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { LINK, TENANT_HOST } from '@/test/fixtures/links';
import { resetLinkRequests, seenBackendRequests, seenBffPosts } from '@/test/msw/handlers/links';
import LinkPage, { dynamic, metadata } from './page';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));
vi.mock('next/headers', () => ({
  headers: async () => new Headers({ host: TENANT_HOST }),
}));

async function open(token: string) {
  const element = await LinkPage({ params: Promise.resolve({ token }) });
  return render(element as React.ReactElement);
}

beforeEach(() => {
  resetLinkRequests();
});

describe('the link page (server)', () => {
  it('hands the link to the reader in the browser, and reads nothing itself', async () => {
    await open(LINK.recorded);
    expect(screen.getByRole('status')).toHaveTextContent('Opening your link');
    expect(seenBackendRequests).toHaveLength(0);
    expect(seenBffPosts).toHaveLength(0);
  });

  it('treats a token that cannot be a link as expired, without any request', async () => {
    await open('not/a/link');
    expect(screen.getByRole('heading', { level: 1, name: 'This link has expired' })).toBeInTheDocument();
    expect(seenBackendRequests).toHaveLength(0);
  });

  it('asks the browser not to send the link address as a referrer, and never caches or indexes the page', () => {
    expect(metadata).toMatchObject({ referrer: 'no-referrer', robots: { index: false, follow: false } });
    expect(dynamic).toBe('force-dynamic');
  });
});
