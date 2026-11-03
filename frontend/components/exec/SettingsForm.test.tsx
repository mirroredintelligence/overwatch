import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { DEFAULT_ALERT_PREFERENCES, type AlertPreferences } from '@/lib/exec/alertPrefs';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { SettingsForm } from './SettingsForm';

const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));

const sent: { body: AlertPreferences }[] = [];

const LEADERS = [
  { id: 'pr-0101', name: 'Sample Lead One' },
  { id: 'pr-0102', name: 'Sample Lead Two' },
];

// The quiet hours and escalation sit in one disclosure; the page has one save for everything.
const escalationRow = () => screen.getByRole('button', { name: /Quiet hours and escalation/ });

beforeEach(() => {
  sent.length = 0;
  server.use(
    http.put('/api/bff/exec/alert-preferences', async ({ request }) => {
      const body = (await request.json()) as AlertPreferences;
      sent.push({ body });
      return HttpResponse.json(body, { headers: { 'Cache-Control': 'no-store' } });
    }),
  );
});

describe('SettingsForm', () => {
  it('sends the whole state, with the chosen window and deputy, and confirms the save', async () => {
    render(<SettingsForm initial={{ ...DEFAULT_ALERT_PREFERENCES, deputy: '' }} />);
    await userEvent.click(escalationRow());
    await userEvent.click(screen.getByRole('button', { name: '30 min' }));
    fireEvent.change(screen.getByLabelText('Then alert'), { target: { value: 'Deputy COO' } });
    await userEvent.click(screen.getByRole('button', { name: 'Save my alerts' }));

    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]?.body).toEqual(expect.objectContaining({ ackMinutes: 30, deputy: 'Deputy COO', weeklySummary: false }));
    expect(await screen.findByText('Your choices are saved.')).toBeInTheDocument();
  });

  it('refuses to send when the deputy is empty, and opens the escalation so the field is seen', async () => {
    render(<SettingsForm initial={{ ...DEFAULT_ALERT_PREFERENCES, deputy: '' }} />);
    await userEvent.click(screen.getByRole('button', { name: 'Save my alerts' }));
    expect(screen.getByText('Enter who to alert next')).toBeInTheDocument();
    expect(escalationRow()).toHaveAttribute('aria-expanded', 'true');
    expect(sent).toHaveLength(0);
  });

  it('refuses to send a deputy who is no longer a leader, and says so once the escalation is open', async () => {
    render(<SettingsForm initial={{ ...DEFAULT_ALERT_PREFERENCES, deputy: 'pr-9999' }} leaders={LEADERS} />);
    await userEvent.click(screen.getByRole('button', { name: 'Save my alerts' }));
    expect(screen.getByText('Enter who to alert next')).toBeInTheDocument();
    expect(screen.getByText('Your saved deputy is no longer a leader. Choose another.')).toBeInTheDocument();
    expect(sent).toHaveLength(0);
  });

  it('keeps the escalation closed at first, and says in one line what it holds', () => {
    render(<SettingsForm initial={{ ...DEFAULT_ALERT_PREFERENCES, deputy: 'pr-0042' }} />);
    expect(escalationRow()).toHaveAttribute('aria-expanded', 'false');
    expect(screen.getByText('No quiet hours. Deputy alerted after 15 min.')).toBeInTheDocument();
  });

  it('has one save for the whole page, and says when the changes apply', async () => {
    render(<SettingsForm initial={{ ...DEFAULT_ALERT_PREFERENCES, deputy: 'pr-0042' }} />);
    await userEvent.click(escalationRow());
    expect(screen.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save my alerts' })).toBeInTheDocument();
    expect(screen.getByText('Saved changes apply from the next alert.')).toBeInTheDocument();
  });

  it('shows the save failure without losing the choices', async () => {
    server.use(http.put('/api/bff/exec/alert-preferences', () => HttpResponse.json({ code: 'exception' }, { status: 503 })));
    render(<SettingsForm initial={{ ...DEFAULT_ALERT_PREFERENCES, deputy: 'pr-0042' }} />);
    await userEvent.click(escalationRow());
    await userEvent.click(screen.getByRole('button', { name: '10 min' }));
    await userEvent.click(screen.getByRole('button', { name: 'Save my alerts' }));
    expect(await screen.findByText('Could not save your choices. Try again.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '10 min' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<SettingsForm initial={{ ...DEFAULT_ALERT_PREFERENCES, deputy: 'pr-0042' }} />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});

describe('SettingsForm switches', () => {
  it('shows the six alerts as switches with their state in words', () => {
    render(<SettingsForm initial={{ ...DEFAULT_ALERT_PREFERENCES, deputy: 'pr-0042' }} />);
    const weekly = screen.getByRole('switch', { name: /Weekly summary/ });
    expect(within(weekly).getByText('Off')).toBeInTheDocument();
    expect(within(screen.getByRole('switch', { name: /Daily summary/ })).getByText('On')).toBeInTheDocument();
  });
});
