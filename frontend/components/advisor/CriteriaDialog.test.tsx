import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { CriteriaDialog } from './CriteriaDialog';

const CRITERIA = {
  accepts: 'Falls without injury · Frailty · Age 18+ · Postcodes DT1 to DT4 · 08:00 to 20:00',
  excludes: 'Suspected fracture · Head injury on anticoagulants · Needs IV therapy',
  version: 3,
  reviewedOn: '2026-09-12',
  reviewBy: '2026-12-12',
  owner: 'UCR clinical lead',
  overdue: false,
};

function renderDialog(onClose = vi.fn()) {
  render(<CriteriaDialog serviceId="svc-ucr-west" serviceName="UCR West" onClose={onClose} />);
  return onClose;
}

describe('CriteriaDialog (W14)', () => {
  it('shows what the service accepts and does not accept, and the version line', async () => {
    server.use(http.get('/api/bff/services/:id/criteria', () => HttpResponse.json(CRITERIA)));
    renderDialog();

    const dialog = await screen.findByRole('dialog', { name: 'Criteria: UCR West' });
    expect(within(dialog).getByText('Full view')).toBeInTheDocument();
    expect(within(dialog).getByText('Accepts')).toBeInTheDocument();
    expect(within(dialog).getByText(CRITERIA.accepts)).toBeInTheDocument();
    expect(within(dialog).getByText('Does not accept')).toBeInTheDocument();
    expect(within(dialog).getByText(CRITERIA.excludes)).toBeInTheDocument();
    expect(
      within(dialog).getByText('Version 3 · reviewed 12 Sep · review by 12 Dec · owner: UCR clinical lead'),
    ).toBeInTheDocument();
    expect(within(dialog).queryByText(/not reviewed since/)).toBeNull();
  });

  it('shows the overdue warning when the criteria are past their review', async () => {
    server.use(http.get('/api/bff/services/:id/criteria', () => HttpResponse.json({ ...CRITERIA, overdue: true })));
    renderDialog();

    expect(await screen.findByText('Criteria not reviewed since 12 Sep')).toBeInTheDocument();
  });

  it('offers a report link with the service in it, and a Close button', async () => {
    server.use(http.get('/api/bff/services/:id/criteria', () => HttpResponse.json(CRITERIA)));
    const user = userEvent.setup();
    const onClose = renderDialog();
    await screen.findByRole('dialog');

    expect(screen.getByRole('link', { name: 'Report a problem with these criteria' })).toHaveAttribute(
      'href',
      '/help?topic=criteria&service=svc-ucr-west',
    );
    await user.click(screen.getByRole('button', { name: 'Close' }));
    expect(onClose).toHaveBeenCalled();
  });

  it('says so when the criteria cannot be read', async () => {
    server.use(http.get('/api/bff/services/:id/criteria', () => HttpResponse.json({ code: 'not-found' }, { status: 404 })));
    renderDialog();

    expect(await screen.findByText('The criteria could not be read.')).toBeInTheDocument();
  });

  it('has no axe violations when open', async () => {
    server.use(http.get('/api/bff/services/:id/criteria', () => HttpResponse.json(CRITERIA)));
    renderDialog();
    await waitFor(() => expect(screen.getByText(CRITERIA.accepts)).toBeInTheDocument());
    expect((await runAxe(document.body)).violations).toEqual([]);
  });
});
