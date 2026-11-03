import { render, screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { ThanksScreen } from './ThanksScreen';

const { push, replace } = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace }) }));

describe('ThanksScreen', () => {
  it('thanks the reporter with the figure, when it was recorded, and the next update due', async () => {
    const { container } = render(<ThanksScreen serviceId="svc-1" service="UCR West" value={3} at="2026-10-30T10:12:00Z" nextDue="2026-10-30T12:00:00Z" />);
    expect(screen.getByRole('heading', { level: 1, name: 'Thank you' })).toBeInTheDocument();
    expect(screen.getByText('UCR West')).toBeInTheDocument();
    expect(container.querySelector('[data-figure="3"]')).toHaveTextContent('3');
    expect(screen.getByText('referrals')).toBeInTheDocument();
    expect(screen.getByText('Recorded at 10:12.')).toBeInTheDocument();
    expect(screen.getByText('Next update due 12:00')).toBeInTheDocument();
    await screen.findAllByRole('listitem');
    expect(await runAxe(container)).toHaveNoViolations();
    expect(within(container).queryByText(/\d{7,}/)).toBeNull();
  });

  it('lists today newest first, each with its time and figure', async () => {
    render(<ThanksScreen serviceId="svc-1" service="UCR West" value={3} at="2026-10-30T10:12:00Z" nextDue="2026-10-30T12:00:00Z" />);
    const today = screen.getByRole('region', { name: 'Today' });
    const rows = await within(today).findAllByRole('listitem');
    expect(rows.map((row) => row.textContent)).toEqual(['10:123 referrals', '08:152 referrals']);
  });

  it('offers Change it as a button-sized outlined link back to the update', async () => {
    render(<ThanksScreen serviceId="svc-1" service="UCR West" value={3} at="2026-10-30T10:12:00Z" nextDue="2026-10-30T12:00:00Z" />);
    const link = screen.getByRole('link', { name: 'Change it' });
    expect(link).toHaveAttribute('href', '/app/respond/svc-1');
    expect(link).toHaveAttribute('data-variant', 'secondary');
    await screen.findAllByRole('listitem');
  });

  it('shows the instants as London clock time, and says nothing of a next update the back end did not give', async () => {
    render(<ThanksScreen serviceId="svc-1" service="UCR West" value={3} at="2026-07-01T10:12:00Z" nextDue="" />);
    expect(screen.getByText('Recorded at 11:12.')).toBeInTheDocument();
    expect(screen.queryByText(/Next update due/)).toBeNull();
    await screen.findAllByRole('listitem');
  });

  it('lists nothing, and does not fail, when today’s reports cannot be read', async () => {
    server.use(http.get('/api/bff/reporter/services/:serviceId/history', () => HttpResponse.json({ code: 'exception' }, { status: 502 })));
    render(<ThanksScreen serviceId="svc-1" service="UCR West" value={3} at="2026-10-30T10:12:00Z" nextDue="" />);
    expect(screen.getByRole('heading', { name: 'Thank you' })).toBeInTheDocument();
    expect(screen.queryAllByRole('listitem')).toHaveLength(0);
  });

  it('sends a 401 on reading today to the PIN screen', async () => {
    server.use(http.get('/api/bff/reporter/services/:serviceId/history', () => HttpResponse.json({ code: 'no-session' }, { status: 401 })));
    render(<ThanksScreen serviceId="svc-1" service="UCR West" value={3} at="2026-10-30T10:12:00Z" nextDue="" />);
    await vi.waitFor(() => expect(replace).toHaveBeenCalledWith('/app/pin'));
  });
});
