import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { resetCsrfCache } from '@/lib/advisor/browser';
import { runAxe } from '@/test/a11y';
import { byEl } from '@/test/el';
import { OPTIONS_EMPTY_VIEW, OPTIONS_VIEW } from '@/test/fixtures/options';
import { resetSeenAdvisorRequests, seenOptionsReads } from '@/test/msw/handlers/advisor';
import { server } from '@/test/msw/server';
import { http, HttpResponse } from 'msw';
import { OptionsList } from './OptionsList';

beforeEach(() => {
  resetCsrfCache();
  resetSeenAdvisorRequests();
});

describe('OptionsList (W13)', () => {
  it('renders the count heading and the sort line, from the options the back end sent', async () => {
    render(<OptionsList caseId="4821" onRequest={vi.fn()} onCriteria={vi.fn()} onPhoned={vi.fn()} onAskClinical={vi.fn()} />);

    expect(await screen.findByRole('heading', { name: "3 services meet this patient's criteria" })).toBeInTheDocument();
    expect(screen.getByText('Sorted by travel time. Not ranked.')).toBeInTheDocument();
  });

  it('says "1 service" in the singular', async () => {
    const one = OPTIONS_VIEW.options[0];
    server.use(http.get('/api/bff/cases/:ref/options', () => HttpResponse.json({ ...OPTIONS_VIEW, options: [one], notSuitable: [] })));
    render(<OptionsList caseId="4821" onRequest={vi.fn()} onCriteria={vi.fn()} onPhoned={vi.fn()} onAskClinical={vi.fn()} />);

    expect(await screen.findByRole('heading', { name: "1 service meets this patient's criteria" })).toBeInTheDocument();
  });

  it('cards appear in the order received, with no rank or "best" label', async () => {
    render(<OptionsList caseId="4821" onRequest={vi.fn()} onCriteria={vi.fn()} onPhoned={vi.fn()} onAskClinical={vi.fn()} />);
    await screen.findByRole('heading', { name: "3 services meet this patient's criteria" });

    const names = screen.getAllByRole('article').map((card) => card.getAttribute('aria-label'));
    expect(names).toEqual(['UCR West', 'Community hospital · Ward B', 'Hospital at home']);
    expect(screen.queryByText(/best|^\d\.$/i)).toBeNull();
  });

  it('with no service that fits, says so and shows the placeholder heading (W16 replaces it)', async () => {
    server.use(http.get('/api/bff/cases/:ref/options', () => HttpResponse.json(OPTIONS_EMPTY_VIEW)));
    render(<OptionsList caseId="4821" onRequest={vi.fn()} onCriteria={vi.fn()} onPhoned={vi.fn()} onAskClinical={vi.fn()} />);

    expect(await screen.findByRole('heading', { name: 'No service fits right now' })).toBeInTheDocument();
  });

  it('the card buttons reach the page through their props with the service id', async () => {
    const user = userEvent.setup();
    const onRequest = vi.fn();
    const onCriteria = vi.fn();
    const onPhoned = vi.fn();
    render(<OptionsList caseId="4821" onRequest={onRequest} onCriteria={onCriteria} onPhoned={onPhoned} onAskClinical={vi.fn()} />);
    await screen.findByRole('heading', { name: "3 services meet this patient's criteria" });
    const ucr = screen.getByRole('article', { name: 'UCR West' });

    await user.click(within(ucr).getByRole('button', { name: 'Request booking' }));
    await user.click(within(ucr).getByRole('button', { name: 'I phoned' }));
    await user.click(within(ucr).getByRole('button', { name: 'Criteria' }));

    expect(onRequest).toHaveBeenCalledWith('svc-ucr-west');
    expect(onPhoned).toHaveBeenCalledWith('svc-ucr-west');
    expect(onCriteria).toHaveBeenCalledWith('svc-ucr-west');
  });

  it('shows the footer note and the three next steps', async () => {
    render(<OptionsList caseId="4821" onRequest={vi.fn()} onCriteria={vi.fn()} onPhoned={vi.fn()} onAskClinical={vi.fn()} />);
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
    render(<OptionsList caseId="4821" onRequest={vi.fn()} onCriteria={vi.fn()} onPhoned={vi.fn()} onAskClinical={vi.fn()} />);
    const card = await screen.findByRole('article', { name: 'Other unit' });

    expect(screen.getAllByText('Read only. You cannot book or change these services from here. Phone the service to check.')).toHaveLength(1);
    expect(within(card).queryByRole('button', { name: 'Request booking' })).toBeNull();
  });

  it('reads the options once per page load, not again on focus', async () => {
    render(<OptionsList caseId="4821" onRequest={vi.fn()} onCriteria={vi.fn()} onPhoned={vi.fn()} onAskClinical={vi.fn()} />);
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
    const { container } = render(<OptionsList caseId="4821" onRequest={vi.fn()} onCriteria={vi.fn()} onPhoned={vi.fn()} onAskClinical={vi.fn()} />);
    expect(screen.getByText('Loading the options.')).toBeInTheDocument();
    await waitFor(() => expect(byEl('ADV-OPT-NUMBER', container)).toBeInTheDocument());

    expect((await runAxe(container)).violations).toEqual([]);
  });
});
