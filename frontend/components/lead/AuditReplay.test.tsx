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
  it('shows the reference, the decision time, and the words of the screen', async () => {
    render(<AuditReplay reference="4821" />);
    expect(await screen.findByRole('heading', { name: 'What the advisor saw' })).toBeInTheDocument();
    expect(screen.getByText('Audit replay')).toBeInTheDocument();
    expect(screen.getByText('Reference 4821 · 23 Oct 14:13:20')).toBeInTheDocument();
    expect(screen.getByText('Criteria version 3')).toBeInTheDocument();
  });

  it('shows one row per service shown, with its name, status word, figure and data age', async () => {
    render(<AuditReplay reference="4821" />);
    const rows = await screen.findAllByRole('listitem', { name: /.*/ });
    const west = rows.find((row) => row.textContent?.includes('UCR West')) as HTMLElement;
    expect(west).toHaveTextContent('Accepting');
    expect(west).toHaveTextContent('4');
    expect(west).toHaveTextContent('9 min old');
  });

  it('shows the timeline in time order, each line with its London time', async () => {
    render(<AuditReplay reference="4821" />);
    const timeline = await screen.findByRole('list', { name: 'Timeline' });
    expect(within(timeline).getAllByRole('listitem').map((item) => item.textContent)).toEqual([
      '14:12 Case 4821 opened',
      '14:13 Three options shown',
      '14:16 Booking request sent to UCR West',
      '14:19 Confirmed by text',
    ]);
  });

  it('says it is read-only and was opened for audit, and offers the export', async () => {
    render(<AuditReplay reference="4821" />);
    expect(await screen.findByText('Read-only. Opened for audit, with a log of who looked.')).toBeInTheDocument();
    const link = screen.getByRole('link', { name: 'Export for review' });
    expect(link).toHaveAttribute('href', '/api/bff/lead/audit/4821/export');
    expect(link).toHaveAttribute('data-el', 'LEAD-AUDIT-EXPORT-BTN');
  });

  it.each([404, 403])('says there is no record, with the same words, when the answer is %s', async (status) => {
    server.use(http.get('/api/bff/lead/audit/:ref', () => HttpResponse.json({ code: 'not-found' }, { status })));
    render(<AuditReplay reference="4821" />);
    expect(await screen.findByRole('alert')).toHaveTextContent('No record for that reference.');
    expect(screen.queryByRole('list', { name: 'Timeline' })).not.toBeInTheDocument();
  });

  it('warns that the replay did not pass its integrity check, and does not hide it', async () => {
    server.use(http.get('/api/bff/lead/audit/:ref', () => HttpResponse.json({ ...AUDIT_4821, chainOk: false })));
    render(<AuditReplay reference="4821" />);
    expect(await screen.findByRole('alert')).toHaveTextContent('did not pass its integrity check');
  });

  it('has no axe violations', async () => {
    const { container } = render(<AuditReplay reference="4821" />);
    await screen.findByRole('list', { name: 'Timeline' });
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
