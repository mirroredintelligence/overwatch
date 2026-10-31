import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { resetCsrfCache } from '@/lib/advisor/browser';
import { byEl } from '@/test/el';
import { resetSeenAdvisorRequests, seenOutcomePosts } from '@/test/msw/handlers/advisor';
import { server } from '@/test/msw/server';
import { OutcomeForm } from './OutcomeForm';

// The back end refuses "accepted and booked" and "redirected" without the service the patient went to,
// and refuses a destination on any other outcome (RecordOutcome.check_destination), so the form asks
// for the service for those two and for nothing else (W15).

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

beforeEach(() => {
  resetCsrfCache();
  resetSeenAdvisorRequests();
});

describe('the destination of an outcome (W15)', () => {
  it('asks which service the call went to for "Accepted and booked", and saves with it', async () => {
    const user = userEvent.setup();
    const onClosed = vi.fn();
    render(<OutcomeForm caseId="case-1" preselect={null} onClosed={onClosed} />);

    await user.click(byEl('ADV-FIN-OUTCOME-ACCEPTED'));
    const group = await screen.findByRole('group', { name: 'Which service did the call go to?' });
    expect(byEl('ADV-FIN-SAVE-BTN')).toBeDisabled();

    await user.click(await screen.findByRole('button', { name: 'UCR West' }));
    expect(group).toBeInTheDocument();
    await user.click(byEl('ADV-FIN-SAVE-BTN'));

    await waitFor(() => expect(seenOutcomePosts).toHaveLength(1));
    expect(seenOutcomePosts[0]?.body).toEqual({ outcome: 'accepted-and-booked', destinationServiceId: 'svc-ucr-west' });
    await waitFor(() => expect(onClosed).toHaveBeenCalled());
  });

  it('asks for the service for "Redirected" too', async () => {
    const user = userEvent.setup();
    render(<OutcomeForm caseId="case-1" preselect={null} onClosed={vi.fn()} />);

    await user.click(byEl('ADV-FIN-OUTCOME-REDIRECTED'));

    expect(await screen.findByRole('group', { name: 'Which service did the call go to?' })).toBeInTheDocument();
  });

  it.each(['ADV-FIN-OUTCOME-DECLINED', 'ADV-FIN-OUTCOME-CANCELLED'])('asks for no service for %s, and sends none', async (id) => {
    const user = userEvent.setup();
    render(<OutcomeForm caseId="case-1" preselect={null} onClosed={vi.fn()} />);

    await user.click(byEl(id));
    expect(screen.queryByRole('group', { name: 'Which service did the call go to?' })).toBeNull();
    await user.click(byEl('ADV-FIN-SAVE-BTN'));

    await waitFor(() => expect(seenOutcomePosts).toHaveLength(1));
    expect(seenOutcomePosts[0]?.body).not.toHaveProperty('destinationServiceId');
  });

  it('drops the chosen service when the advisor changes to an outcome that takes none', async () => {
    const user = userEvent.setup();
    render(<OutcomeForm caseId="case-1" preselect={null} onClosed={vi.fn()} />);

    await user.click(byEl('ADV-FIN-OUTCOME-ACCEPTED'));
    await user.click(await screen.findByRole('button', { name: 'UCR West' }));
    await user.click(byEl('ADV-FIN-OUTCOME-DECLINED'));
    await user.click(byEl('ADV-FIN-SAVE-BTN'));

    await waitFor(() => expect(seenOutcomePosts).toHaveLength(1));
    expect(seenOutcomePosts[0]?.body).toEqual({ outcome: 'declined' });
  });

  it('says so, and lets the advisor try again, when the services cannot be read: the outcome cannot be saved without one', async () => {
    server.use(http.get('/api/bff/cases/:ref/options', () => HttpResponse.json({ code: 'exception' }, { status: 502 }), { once: true }));
    const user = userEvent.setup();
    render(<OutcomeForm caseId="case-1" preselect={null} onClosed={vi.fn()} />);

    await user.click(byEl('ADV-FIN-OUTCOME-ACCEPTED'));
    expect(await screen.findByText('The services could not be read.')).toBeInTheDocument();
    expect(byEl('ADV-FIN-SAVE-BTN')).toBeDisabled();

    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('button', { name: 'UCR West' })).toBeInTheDocument();
  });
});

describe('the services offered as the destination (KI-349)', () => {
  it('asks the back end for the viewer\'s own services only, and never offers a network service', async () => {
    const seenQueries: string[] = [];
    server.use(
      http.get('/api/bff/cases/:ref/options', ({ request }) => {
        seenQueries.push(new URL(request.url).search);
        return HttpResponse.json({
          shownAt: '2026-10-30T14:00:00Z',
          options: [
            { serviceId: 'svc-own', name: 'Own unit', network: null },
            { serviceId: 'net-1', name: 'Neighbour unit', network: { organisation: 'Neighbouring', source: 'x' } },
          ],
          notSuitable: [],
        });
      }),
    );
    const user = userEvent.setup();
    render(<OutcomeForm caseId="case-1" preselect={null} onClosed={vi.fn()} />);

    await user.click(byEl('ADV-FIN-OUTCOME-ACCEPTED'));

    expect(await screen.findByRole('button', { name: 'Own unit' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Neighbour unit' })).toBeNull();
    expect(seenQueries).toEqual(['?only=own']);
  });
});
