import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { CRITERIA_BODY } from '@/test/fixtures/network';
import { parseCriteria } from '@/lib/network/parse';
import { networkBffHandlers, resetNetworkBff, seenNetworkBff } from '@/test/msw/handlers/networkBff';
import { server } from '@/test/msw/server';
import { NetworkCriteriaDialog } from './NetworkCriteriaDialog';

// WB11 (docs/design/network-ui.md sections 4 and 9, the criteria dialog variant): the current criteria of
// ANOTHER organisation's service, read only. Current version only: no reason, no owner, no history; and no
// "Report a problem with these criteria", because that message would go to an organisation the viewer cannot
// message. The service is the listing's reference; the network is the one the server offered.

function open(rowRef = 'lst-0001', onClose = vi.fn()) {
  server.use(...networkBffHandlers);
  resetNetworkBff();
  render(<NetworkCriteriaDialog networkId="net-sample" rowRef={rowRef} serviceName="UCR West" organisationName="Sample Area A" onClose={onClose} />);
  return onClose;
}

describe('NetworkCriteriaDialog', () => {
  it('shows the current criteria of the service, read only, named for the service and its organisation', async () => {
    open();
    const dialog = await screen.findByRole('dialog', { name: 'Criteria: UCR West' });
    expect(dialog).toHaveAttribute('data-el', 'ADV-CRIT-DIALOG');
    expect(await within(dialog).findByText(/Accepts/)).toBeInTheDocument();
    expect(within(dialog).getByText(/Does not accept/)).toBeInTheDocument();
    expect(within(dialog).getByText(/Ages: /)).toBeInTheDocument();
    expect(within(dialog).getByText(/Districts: /)).toBeInTheDocument();
    expect(within(dialog).getByText(/Review by /)).toBeInTheDocument();
    expect(within(dialog).getByText('Shared by Sample Area A')).toBeInTheDocument();
  });

  it('has no way to report a problem, no reason, no owner and no history', async () => {
    open();
    const dialog = await screen.findByRole('dialog');
    await within(dialog).findByText(/Accepts/);
    expect(within(dialog).queryByRole('link', { name: /Report a problem/ })).toBeNull();
    expect(within(dialog).queryByRole('button', { name: /Report a problem/ })).toBeNull();
    expect(dialog.textContent).not.toMatch(/owner|reason|history|reviewed/i);
    expect(within(dialog).getByRole('button', { name: 'Close' })).toBeInTheDocument();
  });

  it('asks the BFF for the one network’s criteria only, naming the network by the one key', async () => {
    open();
    await screen.findByText(/Accepts/);
    expect(seenNetworkBff).toEqual([{ path: '/api/bff/network/criteria', query: 'networkId=net-sample' }]);
  });

  it('says "and over" for a service with no upper age limit', async () => {
    const body = { ...CRITERIA_BODY, entries: [{ ...CRITERIA_BODY.entries[0], age_max: null }] };
    server.use(http.get('/api/bff/network/criteria', () => HttpResponse.json(parseCriteria(body, 'backend'))));
    render(<NetworkCriteriaDialog networkId="net-sample" rowRef="lst-0001" serviceName="UCR West" organisationName="Sample Area A" onClose={() => {}} />);
    expect(await screen.findByText('Ages: 18 and over')).toBeInTheDocument();
  });

  it('says no criteria are shared for a service that shared none', async () => {
    open('lst-9999');
    expect(await screen.findByText('No criteria shared. Phone the service to check.')).toBeInTheDocument();
  });

  it('says the criteria could not be read, and offers only Close, when the read fails', async () => {
    server.use(http.get('/api/bff/network/criteria', () => HttpResponse.json({ code: 'unavailable' }, { status: 503 })));
    render(<NetworkCriteriaDialog networkId="net-sample" rowRef="lst-0001" serviceName="UCR West" organisationName="Sample Area A" onClose={() => {}} />);
    expect(await screen.findByText('The criteria could not be read. Phone the service to check.')).toBeInTheDocument();
  });

  it('closes on Close and on Escape, and puts the focus back where it was', async () => {
    const user = userEvent.setup();
    const opener = document.createElement('button');
    document.body.append(opener);
    opener.focus();
    const onClose = open();
    await screen.findByText(/Accepts/);
    await user.click(screen.getByRole('button', { name: 'Close' }));
    expect(onClose).toHaveBeenCalledTimes(1);
    await user.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledTimes(2);
    opener.remove();
  });

  it('has no axe violations', async () => {
    open();
    const dialog = await screen.findByRole('dialog');
    await within(dialog).findByText(/Accepts/);
    expect(await runAxe(dialog)).toHaveNoViolations();
  });
});
