import { render, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { MyServices } from './MyServices';

const { push, replace } = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace }) }));

describe('MyServices', () => {
  it('says how to add a service and passes axe', async () => {
    const { container } = render(<MyServices />);
    expect(await screen.findByRole('heading', { name: 'My services' })).toBeInTheDocument();
    expect(
      screen.getByText('To add a service, ask the SPOA shift lead. New services are added by invitation and checked.'),
    ).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('renders the three state texts from the list', async () => {
    server.use(
      http.get('/api/bff/reporter/services', () =>
        HttpResponse.json({
          services: [
            { id: 'a', name: 'UCR West', state: 'confirmed', recordedValue: 3, unitLabel: 'referrals', at: '10:12', nextDue: '12:00', pendingAcceptance: false },
            { id: 'b', name: 'UCR East', state: 'due', recordedValue: 1, unitLabel: 'referral', at: '08:15', nextDue: '12:00', replyBy: '10:30', pendingAcceptance: false },
            { id: 'c', name: 'UCR North', state: 'paused', recordedValue: 0, unitLabel: 'referrals', at: '08:00', nextDue: '08:00', pausedUntil: '08:00 tomorrow', pendingAcceptance: false },
          ],
        }),
      ),
    );
    render(<MyServices />);
    expect(await screen.findByText('Confirmed 10:12 · Next due 12:00')).toBeInTheDocument();
    expect(screen.getByText('Due now · By 10:30')).toBeInTheDocument();
    expect(screen.getByText('Paused · Until 08:00 tomorrow')).toBeInTheDocument();
  });
});
