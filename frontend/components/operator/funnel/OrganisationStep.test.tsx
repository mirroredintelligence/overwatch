import { render, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { VIEW_DETAIL_PROVISIONING } from '@/test/fixtures/operator';
import { resetOperatorWrites, seenOperatorWrites } from '@/test/msw/handlers/operator';
import { server } from '@/test/msw/server';
import { TenantDetail } from '../TenantDetail';

// Step 1 of an organisation's page: the NHS record, as the board (O4, part 1) shows it: one checked row, read-only.

beforeEach(() => resetOperatorWrites());

async function open(detail: unknown = VIEW_DETAIL_PROVISIONING) {
  server.use(http.get('/api/bff/platform/tenants/:id', () => HttpResponse.json(detail as Record<string, unknown>)));
  render(<TenantDetail tenantId="trust-b" />);
  await screen.findByRole('heading', { level: 1, name: 'Sample Area B' });
  await waitFor(() => expect(screen.queryByText('Loading.')).not.toBeInTheDocument());
  return screen.getByRole('region', { name: 'Check the organisation' });
}

describe('step 1: check the organisation', () => {
  it('shows the NHS record as one checked row: name, NHS code and where the organisation stands, in one line', async () => {
    const card = await open();
    const row = within(card).getByText('NHS record checked').closest('[data-state]') as HTMLElement;
    expect(row).toHaveAttribute('data-state', 'done');
    expect(row).toHaveTextContent('Sample Area B · RYY02 · Being set up');
    expect(within(row).getByText('Done')).toBeInTheDocument();
  });

  it('says there is no NHS code when the organisation has none', async () => {
    const card = await open({ ...VIEW_DETAIL_PROVISIONING, tenant: { ...VIEW_DETAIL_PROVISIONING.tenant, odsCode: null, organisationType: 'other' } });
    expect(within(card).getByText('NHS record checked').closest('[data-state]')).toHaveTextContent('Sample Area B · No NHS code · Being set up');
  });

  it('keeps the facts in plain words, read only, and the identifiers under technical details', async () => {
    const card = await open();
    expect(within(card).getByText(/cannot be changed here/)).toBeInTheDocument();
    for (const word of ['Legal name', 'Type', 'NHS code', 'Country', 'Time zone']) expect(within(card).getByText(word, { selector: 'dt' })).toBeInTheDocument();
    expect(within(card).getByText('Sample Area B Organisation')).toBeInTheDocument();
    expect(within(card).getByText('Integrated care board')).toBeInTheDocument();
    expect(within(card).getByText('United Kingdom')).toBeInTheDocument();
    expect(within(card).getByText('Europe/London')).toBeInTheDocument();
    expect(within(card).queryByRole('button')).not.toBeInTheDocument();
    expect(within(card).queryByRole('textbox')).not.toBeInTheDocument();
    const details = within(card).getByText('Technical details').closest('details') as HTMLElement;
    expect(details).not.toHaveAttribute('open');
    expect(within(details).getByText('trust-b')).toBeInTheDocument();
    expect(seenOperatorWrites).toEqual([]);
  });

  it('has no accessibility violations', async () => {
    await open();
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});
