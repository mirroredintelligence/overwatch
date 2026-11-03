import { byEl } from '@/test/el';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { resetCsrfCache } from '@/lib/advisor/browser';
import { runAxe } from '@/test/a11y';
import { CASE_ID, CSRF_TOKEN, resetSeenAdvisorRequests, seenCaseCreates } from '@/test/msw/handlers/advisor';
import { networkBffHandlers } from '@/test/msw/handlers/networkBff';
import { server } from '@/test/msw/server';
import AdvisorHomePage from './page';

const push = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }));

beforeEach(() => {
  push.mockReset();
  resetCsrfCache();
  resetSeenAdvisorRequests();
});

describe('advisor home: the scope header (WB11, W10-K3)', () => {
  it('says it shows our organisation and offers the network home, when the organisation is in a network', async () => {
    server.use(...networkBffHandlers);
    render(<AdvisorHomePage />);
    const header = screen.getByRole('region', { name: 'Which board you are viewing' });
    expect(header).toHaveTextContent('Showing: Our organisation');
    const nav = await within(header).findByRole('navigation', { name: 'Choose the board' });
    expect(within(nav).getByRole('link', { name: 'Network' })).toHaveAttribute('href', '/network/home');
    expect(within(nav).getByRole('link', { name: 'Our organisation' })).toHaveAttribute('href', '/advisor');
  });

  it('shows the label and no switch when the organisation is in no network', async () => {
    server.use(http.get('/api/bff/network', () => HttpResponse.json({ ownOrganisation: 'Sample Area A', networks: [] })));
    render(<AdvisorHomePage />);
    await waitFor(() => expect(byEl('ADV-HOME-COUNT-ACCEPTING')).toHaveTextContent('4'));
    expect(screen.getByRole('region', { name: 'Which board you are viewing' })).toHaveTextContent('Showing: Our organisation');
    expect(screen.queryByRole('navigation', { name: 'Choose the board' })).toBeNull();
  });
});

describe('advisor home (W10)', () => {
  it('shows "Ready for calls" and the five board counts from the sample board', async () => {
    render(<AdvisorHomePage />);

    expect(screen.getByRole('heading', { name: 'Ready for calls' })).toBeInTheDocument();
    await waitFor(() => expect(byEl('ADV-HOME-COUNT-ACCEPTING')).toHaveTextContent('4'));
    expect(byEl('ADV-HOME-COUNT-LIMITED')).toHaveTextContent('2');
    expect(byEl('ADV-HOME-COUNT-NOT-ACCEPTING')).toHaveTextContent('1');
    expect(byEl('ADV-HOME-COUNT-OVER-CAPACITY')).toHaveTextContent('1');
    expect(byEl('ADV-HOME-COUNT-NOT-UPDATED')).toHaveTextContent('1');
  });

  it('"Start a new call" posts once with the CSRF header and an Idempotency-Key, then opens the case', async () => {
    const user = userEvent.setup();
    render(<AdvisorHomePage />);

    await user.click(screen.getByRole('button', { name: 'Start a new call' }));

    await waitFor(() => expect(push).toHaveBeenCalledWith(`/advisor/case/${CASE_ID}`));
    expect(seenCaseCreates).toHaveLength(1);
    const sent = seenCaseCreates[0];
    expect(sent.headers.get('x-csrf-token')).toBe(CSRF_TOKEN);
    expect(sent.headers.get('idempotency-key')).toMatch(/^[A-Za-z0-9_-]{8,64}$/);
  });

  it('a double click posts only once', async () => {
    const user = userEvent.setup();
    render(<AdvisorHomePage />);

    const button = screen.getByRole('button', { name: 'Start a new call' });
    await user.dblClick(button);

    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
    expect(seenCaseCreates).toHaveLength(1);
  });

  it('the start button is busy while the case is being created', async () => {
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.post('/api/bff/cases', async () => {
        await gate;
        return HttpResponse.json({ id: CASE_ID }, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    render(<AdvisorHomePage />);

    await user.click(screen.getByRole('button', { name: 'Start a new call' }));
    expect(screen.getByRole('button', { name: 'Start a new call' })).toHaveAttribute('aria-busy', 'true');
    await act(async () => release());
    await waitFor(() => expect(push).toHaveBeenCalled());
  });

  it('links to the wall board view and says nothing from earlier calls is shown', async () => {
    render(<AdvisorHomePage />);

    expect(screen.getByRole('link', { name: 'Open the wall board view' })).toHaveAttribute('href', '/advisor/board');
    expect(screen.getByText('No open cases. Nothing from earlier calls is shown here.')).toBeInTheDocument();
  });

  it('has no axe violations once the counts have loaded', async () => {
    const { container } = render(<AdvisorHomePage />);
    await waitFor(() => expect(byEl('ADV-HOME-COUNT-ACCEPTING')).toHaveTextContent('4'));
    const counts = within(container);
    expect(counts.getByRole('heading', { name: 'Board right now' })).toBeInTheDocument();
    expect((await runAxe(container)).violations).toEqual([]);
  });
});

describe('advisor overview (ADV-02): the call grid, the board stripe and open cases', () => {
  it('shows the five counts as one group in the board order: accepting, limited, over capacity, not accepting, not updated', async () => {
    render(<AdvisorHomePage />);

    const group = await screen.findByRole('group', { name: 'Services by state' });
    await waitFor(() => expect(byEl('ADV-HOME-COUNT-ACCEPTING')).toHaveTextContent('4'));
    const order = within(group)
      .getAllByRole('listitem')
      .map((item) => item.getAttribute('data-status'));
    expect(order).toEqual(['accepting', 'limited', 'over-capacity', 'not-accepting', 'not-updated']);
  });

  it('shows a loading status that says the board is being read', () => {
    render(<AdvisorHomePage />);

    expect(screen.getByText('Loading the board.').closest('[role="status"]')).not.toBeNull();
  });

  it('the stage holds the ready-for-calls card and its one primary button', () => {
    render(<AdvisorHomePage />);

    const stage = byEl('ADV-CALL-STAGE');
    expect(within(stage).getByRole('heading', { name: 'Ready for calls', level: 1 })).toBeInTheDocument();
    expect(within(stage).getByRole('button', { name: 'Start a new call' })).toBeInTheDocument();
    expect(within(stage).getAllByRole('button')).toHaveLength(1);
  });

  it('the side holds "Open cases" with the no-open-cases line', () => {
    render(<AdvisorHomePage />);

    const side = screen.getByRole('complementary', { name: 'Alongside' });
    expect(within(side).getByRole('heading', { name: 'Open cases' })).toBeInTheDocument();
    expect(within(side).getByText('No open cases. Nothing from earlier calls is shown here.')).toBeInTheDocument();
  });

  it('the overview is call stage 0: the summary is folded away and the side is open', () => {
    render(<AdvisorHomePage />);

    expect(byEl('ADV-CALL-STAGE').closest('[data-stage]')).toHaveAttribute('data-stage', '0');
  });
});
