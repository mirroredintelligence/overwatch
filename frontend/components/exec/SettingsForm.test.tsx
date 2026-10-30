import { render, screen, waitFor } from '@testing-library/react';
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
    await userEvent.click(screen.getByRole('button', { name: '30 min' }));
    await userEvent.type(screen.getByLabelText('Then alert'), 'Deputy COO');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]?.body).toEqual(expect.objectContaining({ ackMinutes: 30, deputy: 'Deputy COO', weeklySummary: false }));
    expect(await screen.findByText('Your choices are saved.')).toBeInTheDocument();
  });

  it('refuses to send when the deputy is empty, from either save', async () => {
    render(<SettingsForm initial={{ ...DEFAULT_ALERT_PREFERENCES, deputy: '' }} />);
    await userEvent.click(screen.getByRole('button', { name: 'Save my alerts' }));
    expect(screen.getByText('Enter who to alert next')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(sent).toHaveLength(0);
  });

  it('shows the save failure without losing the choices', async () => {
    server.use(http.put('/api/bff/exec/alert-preferences', () => HttpResponse.json({ code: 'exception' }, { status: 503 })));
    render(<SettingsForm initial={{ ...DEFAULT_ALERT_PREFERENCES, deputy: 'pr-0042' }} />);
    await userEvent.click(screen.getByRole('button', { name: '10 min' }));
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByText('Could not save your choices. Try again.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '10 min' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<SettingsForm initial={{ ...DEFAULT_ALERT_PREFERENCES, deputy: 'pr-0042' }} />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
