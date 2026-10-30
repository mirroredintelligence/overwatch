import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import type { AlertItem } from '@/lib/exec/alerts';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { AlertList } from './AlertList';

const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));

const item = (id: string, extra: Partial<AlertItem> = {}): AlertItem => ({
  id, kind: 'over-capacity', serviceId: 'svc-hah', serviceName: 'Hospital at home', detail: '+4',
  raisedAt: '2026-10-23T13:04:00Z', state: 'new', escalatesAt: null, escalatesTo: null, acknowledgedAt: null, ...extra,
});

const open = [item('al-1'), item('al-2', { serviceName: 'UCR East', kind: 'not-updated', detail: null })];

describe('AlertList', () => {
  it('labels the open tab with its count', () => {
    render(<AlertList open={open} />);
    expect(screen.getByRole('tab', { name: 'Open (2)' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: 'Acknowledged' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Closed' })).toBeInTheDocument();
  });

  it('moves between tabs with the arrow keys', async () => {
    server.use(http.get('/api/bff/exec/alerts', () => HttpResponse.json({ counts: { open: 2 }, items: [] })));
    render(<AlertList open={open} />);
    screen.getByRole('tab', { name: 'Open (2)' }).focus();
    await userEvent.keyboard('{ArrowRight}');
    expect(screen.getByRole('tab', { name: 'Acknowledged' })).toHaveAttribute('aria-selected', 'true');
    await userEvent.keyboard('{ArrowRight}');
    expect(screen.getByRole('tab', { name: 'Closed' })).toHaveFocus();
  });

  it('posts an acknowledgement, removes the card from Open, and shows it on the Acknowledged tab from the back end\'s list', async () => {
    const posted: string[] = [];
    server.use(
      http.post('/api/bff/exec/alerts/:id/acknowledge', ({ params }) => {
        posted.push(String(params.id));
        return HttpResponse.json({ id: params.id, status: 'acknowledged' });
      }),
      http.get('/api/bff/exec/alerts', ({ request }) => {
        expect(new URL(request.url).searchParams.get('state')).toBe('acknowledged');
        return HttpResponse.json({ counts: { open: 1 }, items: [item('al-1', { state: 'acknowledged', acknowledgedAt: '2026-10-23T12:40:00Z' })] });
      }),
    );
    render(<AlertList open={open} />);
    const card = screen.getByRole('article', { name: 'Hospital at home over capacity' });
    await userEvent.click(within(card).getByRole('button', { name: 'Acknowledge' }));
    await waitFor(() => expect(posted).toEqual(['al-1']));
    await userEvent.click(screen.getByRole('tab', { name: 'Acknowledged' }));
    const acknowledged = await screen.findByText(/Acknowledged at 13:40/);
    expect(within(acknowledged.closest('article') as HTMLElement).getByText('Hospital at home over capacity')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Open (1)' })).toBeInTheDocument();
  });

  it('reads the Acknowledged and Closed tabs from the back end when they are opened, and shows what it reads', async () => {
    const states: string[] = [];
    server.use(http.get('/api/bff/exec/alerts', ({ request }) => {
      const state = new URL(request.url).searchParams.get('state') ?? '';
      states.push(state);
      return HttpResponse.json({ counts: { open: 2 }, items: state === 'closed' ? [item('al-8', { state: 'closed', kind: 'not-updated', serviceName: 'UCR West', detail: null })] : [] });
    }));
    render(<AlertList open={open} />);
    await userEvent.click(screen.getByRole('tab', { name: 'Acknowledged' }));
    expect(await screen.findByText('Nothing acknowledged.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('tab', { name: 'Closed' }));
    expect(await screen.findByRole('article', { name: 'UCR West has not updated' })).toBeInTheDocument();
    expect(states).toEqual(['acknowledged', 'closed']);
  });

  it('says the list could not be read, and never says nothing was acknowledged, when the read fails', async () => {
    server.use(http.get('/api/bff/exec/alerts', () => HttpResponse.json({ code: 'exception' }, { status: 503 })));
    render(<AlertList open={open} />);
    await userEvent.click(screen.getByRole('tab', { name: 'Acknowledged' }));
    expect(await screen.findByText('Acknowledged alerts could not be read. Try again shortly.')).toBeInTheDocument();
    expect(screen.queryByText('Nothing acknowledged.')).not.toBeInTheDocument();
  });

  it('restores the card and says so when the acknowledgement fails', async () => {
    server.use(http.post('/api/bff/exec/alerts/:id/acknowledge', () => HttpResponse.json({ code: 'exception' }, { status: 500 })));
    render(<AlertList open={open} />);
    await userEvent.click(within(screen.getByRole('article', { name: 'Hospital at home over capacity' })).getByRole('button', { name: 'Acknowledge' }));
    expect(await screen.findByText('Could not acknowledge. Try again.')).toBeInTheDocument();
    expect(screen.getByRole('article', { name: 'Hospital at home over capacity' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Open (2)' })).toBeInTheDocument();
  });

  it('opens an alert from its Open link', async () => {
    render(<AlertList open={open} />);
    expect(screen.getAllByRole('link', { name: 'Open' })[0]).toHaveAttribute('href', '/planning/alerts/al-1');
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<AlertList open={open} />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
