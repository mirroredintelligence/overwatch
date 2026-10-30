import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { resetCsrfCache } from '@/lib/advisor/browser';
import { runAxe } from '@/test/a11y';
import { byEl } from '@/test/el';
import { OPTIONS_EMPTY_VIEW, OPTIONS_VIEW } from '@/test/fixtures/options';
import { resetSeenAdvisorRequests, seenOptionsReads } from '@/test/msw/handlers/advisor';
import { resetBookingRequests, seenBookingPosts } from '@/test/msw/handlers/bookings';
import { server } from '@/test/msw/server';
import { http, HttpResponse } from 'msw';
import { OptionsList } from './OptionsList';

const push = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }));

beforeEach(() => {
  resetCsrfCache();
  resetSeenAdvisorRequests();
  resetBookingRequests();
  push.mockReset();
  document.cookie = 'diucs_csrf=csrf-value-for-the-list; path=/';
});

describe('OptionsList (W13)', () => {
  it('renders the count heading and the sort line, from the options the back end sent', async () => {
    render(<OptionsList caseId="4821" onCriteria={vi.fn()} onPhoned={vi.fn()} onAskClinical={vi.fn()} />);

    expect(await screen.findByRole('heading', { name: "3 services meet this patient's criteria" })).toBeInTheDocument();
    expect(screen.getByText('Sorted by travel time. Not ranked.')).toBeInTheDocument();
  });

  it('says "1 service" in the singular', async () => {
    const one = OPTIONS_VIEW.options[0];
    server.use(http.get('/api/bff/cases/:ref/options', () => HttpResponse.json({ ...OPTIONS_VIEW, options: [one], notSuitable: [] })));
    render(<OptionsList caseId="4821" onCriteria={vi.fn()} onPhoned={vi.fn()} onAskClinical={vi.fn()} />);

    expect(await screen.findByRole('heading', { name: "1 service meets this patient's criteria" })).toBeInTheDocument();
  });

  it('cards appear in the order received, with no rank or "best" label', async () => {
    render(<OptionsList caseId="4821" onCriteria={vi.fn()} onPhoned={vi.fn()} onAskClinical={vi.fn()} />);
    await screen.findByRole('heading', { name: "3 services meet this patient's criteria" });

    const names = screen.getAllByRole('article').map((card) => card.getAttribute('aria-label'));
    expect(names).toEqual(['UCR West', 'Community hospital · Ward B', 'Hospital at home']);
    expect(screen.queryByText(/best|^\d\.$/i)).toBeNull();
  });

  it('with no service that fits, says so and shows the placeholder heading (W16 replaces it)', async () => {
    server.use(http.get('/api/bff/cases/:ref/options', () => HttpResponse.json(OPTIONS_EMPTY_VIEW)));
    render(<OptionsList caseId="4821" onCriteria={vi.fn()} onPhoned={vi.fn()} onAskClinical={vi.fn()} />);

    expect(await screen.findByRole('heading', { name: 'No service fits right now' })).toBeInTheDocument();
  });

  it('the card buttons reach the page through their props with the service id', async () => {
    const user = userEvent.setup();
    const onCriteria = vi.fn();
    const onPhoned = vi.fn();
    render(<OptionsList caseId="4821" onCriteria={onCriteria} onPhoned={onPhoned} onAskClinical={vi.fn()} />);
    await screen.findByRole('heading', { name: "3 services meet this patient's criteria" });
    const ucr = screen.getByRole('article', { name: 'UCR West' });

    await user.click(within(ucr).getByRole('button', { name: 'I phoned' }));
    await user.click(within(ucr).getByRole('button', { name: 'Criteria' }));

    expect(onPhoned).toHaveBeenCalledWith('svc-ucr-west');
    expect(onCriteria).toHaveBeenCalledWith('svc-ucr-west');
  });

  it('shows the footer note and the three next steps', async () => {
    render(<OptionsList caseId="4821" onCriteria={vi.fn()} onPhoned={vi.fn()} onAskClinical={vi.fn()} />);
    await screen.findByRole('heading', { name: "3 services meet this patient's criteria" });

    expect(
      screen.getByText('No patient name is stored. Postcode and needs are cleared after the call record closes.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Ask clinical advisor' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Record outcome' })).toHaveAttribute('href', '/advisor/case/4821/finish');
    expect(screen.getByRole('link', { name: 'Copy summary for SystmOne' })).toHaveAttribute(
      'href',
      '/advisor/case/4821/finish#summary',
    );
  });

  it('a network option is read only: a read-only note shows once, and no booking actions appear on it', async () => {
    server.use(
      http.get('/api/bff/cases/:ref/options', () =>
        HttpResponse.json({
          ...OPTIONS_EMPTY_VIEW,
          options: [
            {
              serviceId: 'svc-other-unit',
              name: 'Other unit',
              category: null,
              status: 'accepting',
              effectiveAvailable: 2,
              overBy: null,
              unitLabel: 'slots left today',
              travelText: null,
              dataAgeSeconds: 60,
              staleWarning: false,
              criteriaVersion: 1,
              fits: [],
              checks: [],
              phone: null,
              network: { organisation: 'Neighbouring', source: 'Entered by the organisation' },
            },
          ],
        }),
      ),
    );
    render(<OptionsList caseId="4821" onCriteria={vi.fn()} onPhoned={vi.fn()} onAskClinical={vi.fn()} />);
    const card = await screen.findByRole('article', { name: 'Other unit' });

    expect(screen.getAllByText('You cannot book or change these services from here. Phone the service to check.')).toHaveLength(1);
    expect(screen.getByText('Read only')).toBeInTheDocument();
    expect(within(card).queryByRole('button', { name: 'Request booking' })).toBeNull();
  });

  it('reads the options once per page load, not again on focus', async () => {
    render(<OptionsList caseId="4821" onCriteria={vi.fn()} onPhoned={vi.fn()} onAskClinical={vi.fn()} />);
    await screen.findByRole('heading', { name: "3 services meet this patient's criteria" });

    await act(async () => {
      window.dispatchEvent(new Event('focus'));
      document.dispatchEvent(new Event('visibilitychange'));
      fireEvent.focus(window);
    });
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(seenOptionsReads).toEqual(['4821']);
  });

  it('shows the loading line before the options arrive, and has no axe violations once they have', async () => {
    const { container } = render(<OptionsList caseId="4821" onCriteria={vi.fn()} onPhoned={vi.fn()} onAskClinical={vi.fn()} />);
    expect(screen.getByText('Loading the options.')).toBeInTheDocument();
    await waitFor(() => expect(byEl('ADV-OPT-NUMBER', container)).toBeInTheDocument());

    expect((await runAxe(container)).violations).toEqual([]);
  });
});

describe('OptionsList dialogs (W14)', () => {
  it('"Criteria" opens the criteria dialog; Escape closes it and returns focus to the button', async () => {
    server.use(
      http.get('/api/bff/services/:id/criteria', () =>
        HttpResponse.json({ accepts: 'A', excludes: 'B', version: 1, reviewedOn: null, reviewBy: '2099-01-01', owner: null, overdue: false }),
      ),
    );
    const user = userEvent.setup();
    render(<OptionsList caseId="4821" onCriteria={vi.fn()} onPhoned={vi.fn()} onAskClinical={vi.fn()} />);
    await screen.findByRole('heading', { name: "3 services meet this patient's criteria" });
    const button = within(screen.getByRole('article', { name: 'UCR West' })).getByRole('button', { name: 'Criteria' });

    await user.click(button);
    expect(await screen.findByRole('dialog', { name: 'Criteria: UCR West' })).toBeInTheDocument();
    await user.keyboard('{Escape}');

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(button).toHaveFocus();
  });

  it('"I phoned" and "They declined" open their dialogs for that service', async () => {
    const user = userEvent.setup();
    render(<OptionsList caseId="4821" onCriteria={vi.fn()} onPhoned={vi.fn()} onAskClinical={vi.fn()} />);
    await screen.findByRole('heading', { name: "3 services meet this patient's criteria" });
    const card = screen.getByRole('article', { name: 'UCR West' });

    await user.click(within(card).getByRole('button', { name: 'I phoned' }));
    expect(screen.getByRole('dialog', { name: 'I phoned' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    await user.click(within(card).getByRole('button', { name: 'They declined' }));
    expect(screen.getByRole('dialog', { name: 'They declined' })).toBeInTheDocument();
  });

  it('after a saved answer the options are read again, once', async () => {
    const user = userEvent.setup();
    render(<OptionsList caseId="4821" onCriteria={vi.fn()} onPhoned={vi.fn()} onAskClinical={vi.fn()} />);
    await screen.findByRole('heading', { name: "3 services meet this patient's criteria" });
    await user.click(within(screen.getByRole('article', { name: 'UCR West' })).getByRole('button', { name: 'I phoned' }));
    await user.click(screen.getByRole('button', { name: 'Accepting' }));
    await user.type(screen.getByLabelText('How many can they take?'), '2');
    await user.click(byEl('ADV-PHONED-SAVE-BTN'));

    await waitFor(() => expect(seenOptionsReads).toHaveLength(2));
  });
});

describe('OptionsList with no service that fits (W16)', () => {
  it('shows the what-instead options and the reasons, and the widen option reads the options again', async () => {
    server.use(
      http.get('/api/bff/cases/:ref', () =>
        HttpResponse.json({ id: '4821', referrerType: 'gp', ageBand: '80+', postcode: 'DT4 8XX', needs: ['frailty'], urgency: 'within-2-hrs', scores: [], openedAt: null, etag: 'W/"1"' }),
      ),
      http.get('/api/bff/cases/:ref/options', () => {
        seenOptionsReads.push('4821');
        return HttpResponse.json({ ...OPTIONS_EMPTY_VIEW });
      }),
    );
    const user = userEvent.setup();
    render(<OptionsList caseId="4821" onCriteria={vi.fn()} onPhoned={vi.fn()} onAskClinical={vi.fn()} />);

    const widen = await screen.findByRole('button', { name: 'Widen the time: today instead of within 2 hrs' });
    expect(screen.getByRole('heading', { name: 'No service fits right now' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '3 services not suitable, and why' })).toBeInTheDocument();
    await user.click(widen);

    await waitFor(() => expect(seenOptionsReads).toHaveLength(2));
  });
});


describe('the booking control on each card (W13, W20)', () => {
  it('mounts one booking panel per service of the viewer\'s own organisation, and posts the case and the service, once', async () => {
    const user = userEvent.setup();
    render(<OptionsList caseId="case-1" />);
    await screen.findByRole('heading', { name: "3 services meet this patient's criteria" });
    expect(screen.getAllByRole('button', { name: 'Request booking' })).toHaveLength(3);
    const ward = screen.getByRole('article', { name: 'Community hospital · Ward B' });

    await user.click(within(ward).getByRole('button', { name: 'Request booking' }));

    expect(await within(ward).findByText('Requested')).toBeInTheDocument();
    expect(seenBookingPosts).toHaveLength(1);
    expect(seenBookingPosts[0]?.body).toEqual({ caseRef: 'case-1', serviceId: 'svc-ward-b' });
    expect(seenBookingPosts[0]?.csrf).toBe('csrf-value-for-the-list');
    // The other two cards still offer the control: a request is one service's.
    expect(screen.getAllByRole('button', { name: 'Request booking' })).toHaveLength(2);
  });

  it('says the service has a request waiting, on its own card, when the back end refuses a second (409)', async () => {
    server.use(http.post('/api/bff/bookings', () => HttpResponse.json({ code: 'open-request' }, { status: 409 })));
    const user = userEvent.setup();
    render(<OptionsList caseId="case-1" />);
    const ucr = await screen.findByRole('article', { name: 'UCR West' });

    await user.click(within(ucr).getByRole('button', { name: 'Request booking' }));

    expect(await within(ucr).findByText('UCR West already has a request waiting. Phone them instead.')).toBeInTheDocument();
  });

  it('takes a confirmed booking to the outcome and to the summary on the finish screen', async () => {
    const { bookingStore } = await import('@/test/msw/handlers/bookings');
    const { STATE_CONFIRMED } = await import('@/test/fixtures/bookings');
    server.use(http.post('/api/bff/bookings', () => HttpResponse.json(STATE_CONFIRMED, { status: 201 })));
    void bookingStore;
    const user = userEvent.setup();
    render(<OptionsList caseId="case-1" />);
    const ucr = await screen.findByRole('article', { name: 'UCR West' });
    await user.click(within(ucr).getByRole('button', { name: 'Request booking' }));

    await user.click(await within(ucr).findByRole('button', { name: 'Record outcome' }));
    expect(push).toHaveBeenLastCalledWith('/advisor/case/case-1/finish');
    await user.click(within(ucr).getByRole('button', { name: 'Copy summary for SystmOne' }));
    expect(push).toHaveBeenLastCalledWith('/advisor/case/case-1/finish#summary');
  });

  it('"Back to options" after a decline brings the advisor to the list again, and reads nothing new (DEC-636)', async () => {
    const { STATE_DECLINED } = await import('@/test/fixtures/bookings');
    server.use(http.post('/api/bff/bookings', () => HttpResponse.json(STATE_DECLINED, { status: 201 })));
    const user = userEvent.setup();
    render(<OptionsList caseId="case-1" />);
    const ucr = await screen.findByRole('article', { name: 'UCR West' });
    await user.click(within(ucr).getByRole('button', { name: 'Request booking' }));

    await user.click(await within(ucr).findByRole('button', { name: 'Back to options' }));

    expect(document.activeElement).toBe(screen.getByRole('heading', { name: "3 services meet this patient's criteria" }));
    expect(seenOptionsReads).toHaveLength(1);
  });

  it('opens the clinical dialog from the withdrawal alert of a card, and acknowledges nothing (DEC-854, DEC-855)', async () => {
    const { STATE_WITHDRAWN } = await import('@/test/fixtures/bookings');
    const { seenAcknowledgements } = await import('@/test/msw/handlers/bookings');
    server.use(http.post('/api/bff/bookings', () => HttpResponse.json(STATE_WITHDRAWN, { status: 201 })));
    const user = userEvent.setup();
    render(<OptionsList caseId="case-1" />);
    const ucr = await screen.findByRole('article', { name: 'UCR West' });
    await user.click(within(ucr).getByRole('button', { name: 'Request booking' }));

    await user.click(await screen.findByRole('button', { name: 'Ask a clinical advisor' }));

    expect(await screen.findByRole('heading', { name: 'Ask a clinical advisor' })).toBeInTheDocument();
    expect(seenAcknowledgements).toEqual([]);
  });
});
