import { render, screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { AUDIT_4821 } from '@/test/fixtures/lead';
import { server } from '@/test/msw/server';
import { AuditReplay } from './AuditReplay';

// What the advisor saw at the decision (W47). Read-only; the page is not cached, and each opening is audited
// by the back end.

describe('AuditReplay', () => {
  it('shows the heading, the reference with the decision time, and the criteria line', async () => {
    render(<AuditReplay reference="4821" />);
    expect(await screen.findByText('Reference 4821 · decision at 14:13 on Fri 23 Oct')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'What the advisor saw' })).toBeInTheDocument();
    expect(screen.getByText('Criteria version 3 for all services shown.')).toBeInTheDocument();
  });

  it('shows a loading line until the replay arrives', () => {
    render(<AuditReplay reference="4821" />);
    expect(screen.getByText('Loading the replay.')).toBeInTheDocument();
  });

  it('states in words that the replay passed its integrity check', async () => {
    render(<AuditReplay reference="4821" />);
    const status = await screen.findByRole('status');
    expect(status).toHaveTextContent(
      'This replay passed its integrity check. Nothing has been changed since it was recorded.',
    );
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('shows the services shown as a list, with column names, one row per service', async () => {
    render(<AuditReplay reference="4821" />);
    const section = await screen.findByRole('region', { name: 'Services shown' });
    for (const column of ['Service', 'Status', 'Figure', 'Age']) {
      expect(within(section).getByText(column)).toBeInTheDocument();
    }
    const rows = within(screen.getByRole('list', { name: 'Services shown' })).getAllByRole('listitem');
    expect(rows).toHaveLength(3);
  });

  it('shows each service with its name, its status word, its figure and its data age', async () => {
    render(<AuditReplay reference="4821" />);
    const rows = within(await screen.findByRole('list', { name: 'Services shown' })).getAllByRole('listitem');
    const west = rows.find((row) => row.textContent?.includes('UCR West')) as HTMLElement;
    expect(west).toHaveTextContent('Accepting');
    expect(west).toHaveTextContent('4');
    expect(west).toHaveTextContent('9 min old');
    const reablement = rows.find((row) => row.textContent?.includes('Reablement')) as HTMLElement;
    expect(reablement).toHaveTextContent('Not updated');
  });

  it('shows the timeline as an ordered list in time order, each line with its London time', async () => {
    render(<AuditReplay reference="4821" />);
    const timeline = await screen.findByRole('list', { name: 'Timeline' });
    expect(timeline.tagName).toBe('OL');
    expect(within(timeline).getAllByRole('listitem').map((item) => item.textContent)).toEqual([
      '14:12 Case 4821 opened',
      '14:13 Three options shown',
      '14:16 Booking request sent to UCR West',
      '14:19 Confirmed by text',
    ]);
  });

  it('says it is read-only and was opened for audit, and offers the export for the record', async () => {
    render(<AuditReplay reference="4821" />);
    expect(await screen.findByText('Read-only. Opened for audit, with a log of who looked.')).toBeInTheDocument();
    const link = screen.getByRole('link', { name: 'Export for the record' });
    expect(link).toHaveAttribute('href', '/api/bff/lead/audit/4821/export');
    expect(link).toHaveAttribute('data-el', 'LEAD-AUDIT-EXPORT-BTN');
  });

  it.each([404, 403])('says there is no record, with the same words, when the answer is %s', async (status) => {
    server.use(http.get('/api/bff/lead/audit/:ref', () => HttpResponse.json({ code: 'not-found' }, { status })));
    render(<AuditReplay reference="4821" />);
    expect(await screen.findByRole('alert')).toHaveTextContent('No record for that reference.');
    expect(screen.queryByRole('list', { name: 'Timeline' })).not.toBeInTheDocument();
  });

  it('says the replay could not be loaded, and shows no replay, when the server fails', async () => {
    server.use(http.get('/api/bff/lead/audit/:ref', () => HttpResponse.json({ code: 'boom' }, { status: 500 })));
    render(<AuditReplay reference="4821" />);
    expect(await screen.findByRole('alert')).toHaveTextContent('The replay could not be loaded. Try again shortly.');
    expect(screen.queryByRole('list', { name: 'Timeline' })).not.toBeInTheDocument();
  });

  it('warns that the replay did not pass its integrity check, does not say it passed, and does not hide it', async () => {
    server.use(http.get('/api/bff/lead/audit/:ref', () => HttpResponse.json({ ...AUDIT_4821, chainOk: false })));
    render(<AuditReplay reference="4821" />);
    expect(await screen.findByRole('alert')).toHaveTextContent('did not pass its integrity check');
    expect(screen.getByRole('alert')).toHaveTextContent('Do not rely on it until it is checked.');
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    expect(screen.getByRole('list', { name: 'Timeline' })).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const { container } = render(<AuditReplay reference="4821" />);
    await screen.findByRole('list', { name: 'Timeline' });
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
