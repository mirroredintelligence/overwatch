import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetAdminWrites, seenAdminWrites } from '@/test/msw/handlers/tenantAdmin';
import { SAMPLE_CSRF } from '@/test/msw/handlers/staff';
import { server } from '@/test/msw/server';
import { RetentionForm } from './RetentionForm';

// Data retention (TEN-076): how long each class of data is kept and what happens when the time is up. One
// rule per class, or the platform's defaults. No class of data is left without a rule.

beforeEach(() => resetAdminWrites());

async function open() {
  const user = userEvent.setup();
  render(<RetentionForm />);
  await screen.findByRole('heading', { level: 1, name: 'Data retention' });
  await screen.findByRole('table', { name: 'Retention rules' });
  return user;
}

describe('RetentionForm', () => {
  it('has a row for each of the eight classes of data, filled with the rule held, and a blank for one that has none', async () => {
    await open();
    const rows = within(screen.getByRole('table', { name: 'Retention rules' })).getAllByRole('row').slice(1);
    expect(rows).toHaveLength(8);
    const reports = screen.getByRole('row', { name: /Capacity reports/ });
    expect(within(reports).getByLabelText('Days to keep Capacity reports')).toHaveValue(730);
    expect(within(reports).getByLabelText('What happens to Capacity reports')).toHaveValue('summarise');
    const bookings = screen.getByRole('row', { name: /Bookings/ });
    expect(within(bookings).getByLabelText('Days to keep Bookings')).toHaveValue(null);
    const chain = screen.getByRole('row', { name: /Audit chain/ });
    expect(within(chain).getByLabelText('What happens to Audit chain')).toHaveValue('keep');
  });

  it('will not save until every class has an action, and says which is missing', async () => {
    const user = await open();
    await user.click(screen.getByRole('button', { name: 'Save retention rules' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('There is 1 problem');
    expect(screen.getByText('Choose what happens to Bookings.', { selector: 'p' })).toBeInTheDocument();
    expect(seenAdminWrites).toEqual([]);
  });

  it('sends one rule per class, days as a whole number or none, with the CSRF token and a key', async () => {
    const user = await open();
    for (const [cls, days] of [['Bookings', '365'], ['Case audit', '2555'], ['Communications', '90'], ['Telemetry raw', '30'], ['Telemetry aggregates', '730'], ['Safety concerns', '3650']] as const) {
      await user.type(screen.getByLabelText(`Days to keep ${cls}`), days);
      await user.selectOptions(screen.getByLabelText(`What happens to ${cls}`), 'delete');
    }
    await user.click(screen.getByRole('button', { name: 'Save retention rules' }));
    await waitFor(() => expect(seenAdminWrites).toHaveLength(1));
    const write = seenAdminWrites[0]!;
    expect(write).toMatchObject({ method: 'PUT', path: '/api/bff/tenant/retention', csrf: SAMPLE_CSRF });
    const rules = (write.body as { rules: { dataClass: string; keepDays: number | null; action: string }[] }).rules;
    expect(rules).toHaveLength(8);
    expect(rules.find((r) => r.dataClass === 'bookings')).toEqual({ dataClass: 'bookings', keepDays: 365, action: 'delete' });
    expect(rules.find((r) => r.dataClass === 'audit-chain')).toEqual({ dataClass: 'audit-chain', keepDays: null, action: 'keep' });
    expect(await screen.findByRole('status')).toHaveTextContent('Retention rules saved.');
  });

  it('refuses days that are not a whole number of at least 1', async () => {
    const user = await open();
    const days = screen.getByLabelText('Days to keep Capacity reports');
    await user.clear(days);
    await user.type(days, '0');
    await user.click(screen.getByRole('button', { name: 'Save retention rules' }));
    expect(await screen.findByText('Enter a whole number of days, 1 or more, or leave it empty.', { selector: 'p' })).toBeInTheDocument();
    expect(seenAdminWrites).toEqual([]);
  });

  it('uses the platform’s defaults with one confirmed step', async () => {
    const user = await open();
    await user.click(screen.getByRole('button', { name: 'Use the platform defaults' }));
    const dialog = await screen.findByRole('dialog', { name: 'Use the platform defaults?' });
    await user.click(within(dialog).getByRole('button', { name: 'Use the defaults' }));
    await waitFor(() => expect(seenAdminWrites).toHaveLength(1));
    expect(seenAdminWrites[0]?.body).toEqual({ useDefaults: true });
  });

  it('says it could not be saved, and keeps what was typed, on a failure', async () => {
    server.use(http.put('/api/bff/tenant/retention', () => HttpResponse.json({}, { status: 503 })));
    const user = await open();
    const days = screen.getByLabelText('Days to keep Capacity reports');
    await user.clear(days);
    await user.type(days, '800');
    for (const cls of ['Bookings', 'Case audit', 'Communications', 'Telemetry raw', 'Telemetry aggregates', 'Safety concerns']) await user.selectOptions(screen.getByLabelText(`What happens to ${cls}`), 'keep');
    await user.click(screen.getByRole('button', { name: 'Save retention rules' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The retention rules could not be saved. Try again.');
    expect(days).toHaveValue(800);
  });

  it('says it could not load when the read fails, and has no axe violations when it loads', async () => {
    server.use(http.get('/api/bff/tenant/overview', () => HttpResponse.json({}, { status: 503 })));
    const { unmount } = render(<RetentionForm />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not load the retention rules.');
    unmount();
    server.resetHandlers();
    await open();
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});
