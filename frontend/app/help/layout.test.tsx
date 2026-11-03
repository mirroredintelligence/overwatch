import { render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import Layout from './layout';

vi.mock('@/app/StaffShell', () => ({ StaffShell: ({ children }: { children: ReactNode }) => <div>{children}</div> }));

afterEach(() => vi.unstubAllEnvs());

describe('Help layout: the hub column', () => {
  it('offers the three ways in, the safety concern first, each with its one-line reason', () => {
    render(<Layout><p>page</p></Layout>);
    const hub = screen.getByRole('navigation', { name: 'What do you need?' });
    const links = Array.from(hub.querySelectorAll('a'));
    expect(links.map((a) => a.getAttribute('href'))).toEqual(['/help/safety', '/help/problem', '/help/share']);
    expect(screen.getByRole('link', { name: /^Report a safety concern/ })).toHaveTextContent('Goes to the clinical safety officer');
    expect(screen.getByRole('link', { name: /^Something is wrong with the tool/ })).toHaveTextContent('A page, a figure, a message');
    expect(screen.getByRole('link', { name: /^Share my session with support/ })).toHaveTextContent('Makes a code you read out');
  });

  it('always links to "Share my session with support", whatever the old flag says (W56)', () => {
    vi.stubEnv('NEXT_PUBLIC_SUPPORT_SHARING', 'off');
    render(<Layout><p>page</p></Layout>);
    expect(screen.getByRole('link', { name: /^Share my session with support/ })).toHaveAttribute('href', '/help/share');
  });

  it('says to use the usual phone process first when a patient is at risk', () => {
    render(<Layout><p>page</p></Layout>);
    expect(screen.getByText('Urgent and a patient is at risk? Use your usual phone process first.')).toBeInTheDocument();
  });

  it('shows the page beside the hub', () => {
    render(<Layout><p>the page</p></Layout>);
    expect(screen.getByText('the page')).toBeInTheDocument();
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<Layout><main><h1>Help</h1></main></Layout>);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
