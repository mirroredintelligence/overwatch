import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { VIEW_OVERVIEW } from '@/test/fixtures/tenantAdmin';
import { resetAdminWrites, seenAdminWrites } from '@/test/msw/handlers/tenantAdmin';
import { SAMPLE_CSRF } from '@/test/msw/handlers/staff';
import { server } from '@/test/msw/server';
import { DEFAULTS, RetentionForm } from './RetentionForm';

// Data retention (TEN-076): how long each class of data is kept and what happens when the time is up. One
// rule per class, or the platform's defaults. No class of data is left without a rule. One row is editable at a
// time; the two kinds the back end keeps until purge are fixed.

beforeEach(() => resetAdminWrites());

type User = ReturnType<typeof userEvent.setup>;

async function open() {
  const user = userEvent.setup();
  render(<RetentionForm />);
  await screen.findByRole('heading', { level: 1, name: 'Data retention' });
  await screen.findByRole('region', { name: 'Retention at a glance' });
  return user;
}

/** Opens "Review or change" if it is shut, then the row for one kind of data. */
async function editRow(user: User, name: string) {
  const review = screen.getByRole('button', { name: /Review or change/ });
  if (review.getAttribute('aria-expanded') === 'false') await user.click(review);
  await user.click(screen.getByRole('button', { name: `Edit ${name}` }));
}

describe('RetentionForm', () => {
  it('has a row for each of the eight kinds of data: the rule held in words, a row with no rule that says so, and the two kept kinds fixed', async () => {
    await open();
    const rows = within(screen.getByRole('table', { name: 'Retention rules' })).getAllByRole('row').slice(1);
    expect(rows).toHaveLength(8);
    const reports = screen.getByRole('row', { name: /Capacity reports/ });
    expect(within(reports).getByText('730 days')).toBeInTheDocument();
    expect(within(reports).getByText('Summarised')).toBeInTheDocument();
    expect(within(reports).getByRole('button', { name: 'Edit Capacity reports' })).toBeInTheDocument();
    const bookings = screen.getByRole('row', { name: /Bookings/ });
    expect(within(bookings).getByText('Not set')).toBeInTheDocument();
    const chain = screen.getByRole('row', { name: /Audit chain/ });
    expect(within(chain).getByText('No time limit')).toBeInTheDocument();
    expect(within(chain).getByText('Fixed')).toBeInTheDocument();
    expect(within(chain).queryByRole('button')).not.toBeInTheDocument();
    const safety = screen.getByRole('row', { name: /Safety concerns/ });
    expect(within(safety).getByText('Fixed')).toBeInTheDocument();
  });

  it('leads with one answer as a heading and the schedule in words, before any table is opened', async () => {
    await open();
    const glance = screen.getByRole('region', { name: 'Retention at a glance' });
    expect(within(glance).getByRole('heading', { level: 2, name: '2 of 8 kinds of data have a rule' })).toBeInTheDocument();
    expect(within(glance).getByText('2 years, then summarised')).toBeInTheDocument();
    expect(within(glance).getByText('kept, no time limit')).toBeInTheDocument();
    expect(within(glance).getAllByText('not set')).toHaveLength(6);
    expect(screen.getByRole('button', { name: /Review or change/ })).toHaveAttribute('aria-expanded', 'false');
  });

  it('says the platform defaults are in use, shows them, and checks them before go-live, right after they are chosen', async () => {
    const user = await open();
    await user.click(screen.getByRole('button', { name: 'Use the platform defaults' }));
    const dialog = await screen.findByRole('dialog', { name: 'Use the platform defaults?' });
    await user.click(within(dialog).getByRole('button', { name: 'Use the defaults' }));
    const glance = screen.getByRole('region', { name: 'Retention at a glance' });
    expect(await within(glance).findByRole('heading', { level: 2, name: 'The platform defaults are in use' })).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Saved. The platform defaults are in use.');
    expect(within(glance).getByText('7 years, then deleted')).toBeInTheDocument();
    expect(within(glance).queryByText('not set')).not.toBeInTheDocument();
    expect(screen.getByText('Check before go-live')).toBeInTheDocument();
  });

  it('opens one row at a time, with its days and what happens filled in', async () => {
    const user = await open();
    await editRow(user, 'Capacity reports');
    expect(screen.getByLabelText('Days to keep Capacity reports')).toHaveValue(730);
    expect(screen.getByLabelText('What happens to Capacity reports')).toHaveValue('summarise');
    await editRow(user, 'Bookings');
    expect(screen.queryByLabelText('Days to keep Capacity reports')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Days to keep Bookings')).toHaveValue(null);
    expect(screen.getByRole('button', { name: 'Edit Capacity reports' })).toBeInTheDocument();
  });

  it('says what a row needs when it is saved without it, and sends nothing', async () => {
    const user = await open();
    await editRow(user, 'Bookings');
    await user.click(screen.getByRole('button', { name: 'Save Bookings' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('There is 1 problem');
    expect(screen.getByRole('alert')).toHaveTextContent('Choose what happens to Bookings.');
    expect(seenAdminWrites).toEqual([]);
  });

  it('refuses to save a row while other kinds of data have no rule, names them, and sends nothing', async () => {
    const user = await open();
    await editRow(user, 'Bookings');
    await user.type(screen.getByLabelText('Days to keep Bookings'), '365');
    await user.selectOptions(screen.getByLabelText('What happens to Bookings'), 'delete');
    await user.click(screen.getByRole('button', { name: 'Save Bookings' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Set the rules for Case audit, Communications, Telemetry raw, Telemetry aggregates, Safety concerns first, or use the platform defaults.',
    );
    expect(seenAdminWrites).toEqual([]);
  });

  it('sends the edited row with the other seven as held, with the CSRF token and a key, and says what was saved', async () => {
    const user = await open();
    await user.click(screen.getByRole('button', { name: 'Use the platform defaults' }));
    await user.click(within(await screen.findByRole('dialog', { name: 'Use the platform defaults?' })).getByRole('button', { name: 'Use the defaults' }));
    await waitFor(() => expect(seenAdminWrites).toHaveLength(1));
    await editRow(user, 'Bookings');
    const days = screen.getByLabelText('Days to keep Bookings');
    await user.clear(days);
    await user.type(days, '365');
    await user.click(screen.getByRole('button', { name: 'Save Bookings' }));
    await waitFor(() => expect(seenAdminWrites).toHaveLength(2));
    const write = seenAdminWrites[1]!;
    expect(write).toMatchObject({ method: 'PUT', path: '/api/bff/tenant/retention', csrf: SAMPLE_CSRF });
    expect(write.key).not.toBeNull();
    const rules = (write.body as { rules: { dataClass: string; keepDays: number | null; action: string }[] }).rules;
    expect(rules).toHaveLength(8);
    expect(rules.find((r) => r.dataClass === 'bookings')).toEqual({ dataClass: 'bookings', keepDays: 365, action: 'delete' });
    expect(rules.find((r) => r.dataClass === 'capacity-reports')).toEqual({ dataClass: 'capacity-reports', keepDays: 730, action: 'summarise' });
    expect(rules.find((r) => r.dataClass === 'audit-chain')).toEqual({ dataClass: 'audit-chain', keepDays: null, action: 'keep' });
    expect(await screen.findByRole('status')).toHaveTextContent('Saved. Bookings: 1 year, then deleted.');
    expect(screen.queryByLabelText('Days to keep Bookings')).not.toBeInTheDocument();
  });

  it('refuses days that are not a whole number of at least 1', async () => {
    const user = await open();
    await editRow(user, 'Capacity reports');
    const days = screen.getByLabelText('Days to keep Capacity reports');
    await user.clear(days);
    await user.type(days, '0');
    await user.click(screen.getByRole('button', { name: 'Save Capacity reports' }));
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

  it('says it could not be saved, and keeps the row open with what was typed, on a failure', async () => {
    server.use(http.get('/api/bff/tenant/overview', () => HttpResponse.json({ ...VIEW_OVERVIEW, retention: DEFAULTS })));
    server.use(http.put('/api/bff/tenant/retention', () => HttpResponse.json({}, { status: 503 })));
    const user = await open();
    await editRow(user, 'Capacity reports');
    const days = screen.getByLabelText('Days to keep Capacity reports');
    await user.clear(days);
    await user.type(days, '800');
    await user.click(screen.getByRole('button', { name: 'Save Capacity reports' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The retention rules could not be saved. Try again.');
    expect(screen.getByLabelText('Days to keep Capacity reports')).toHaveValue(800);
  });

  it('holds the platform defaults the back end holds (DEC-271), so the two cannot drift apart', () => {
    // Vitest runs from the frontend folder; the back end sits next to it.
    const source = readFileSync(resolve(process.cwd(), '../backend/src/overwatch/domain/model/tenant_records.py'), 'utf8');
    const start = source.indexOf('_DEFAULT_RETENTION: Final = (');
    const end = source.indexOf('\n)', start);
    expect(start).toBeGreaterThan(-1);
    const backEnd = [...source.slice(start, end).matchAll(/TenantRetention\(RetentionClass\.([A-Z_]+), (\d+|None), RetentionAction\.([A-Z_]+)\)/g)].map(
      ([, cls, days, action]) => ({
        dataClass: cls!.toLowerCase().replace(/_/g, '-'),
        keepDays: days === 'None' ? null : Number(days),
        action: action!.toLowerCase(),
      }),
    );
    expect(backEnd).toHaveLength(8);
    expect(DEFAULTS).toEqual(backEnd);
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
