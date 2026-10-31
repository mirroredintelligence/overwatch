import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { resetCsrfCache } from '@/lib/advisor/browser';
import { runAxe } from '@/test/a11y';
import { byEl } from '@/test/el';
import { RADAR_EMPTY, RADAR_NOT_FOUND, RADAR_OUT_OF_AREA, RADAR_VIEW } from '@/test/fixtures/radar';
import { BLANK_CASE, CASE_ETAG } from '@/test/msw/handlers/advisor';
import { server } from '@/test/msw/server';
import { CompareScreen } from './CompareScreen';
import { RadarScreen } from './RadarScreen';
import { WaysScreen } from './WaysScreen';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

const CASE = { ...BLANK_CASE, referrerType: 'gp', ageBand: '80+', postcode: 'DT4 8XX', needs: ['frailty'], urgency: 'within-2-hrs', etag: CASE_ETAG };
let optionsUrls: string[] = [];

function answerWith(options: unknown, caseView: unknown = CASE) {
  server.use(
    http.get('/api/bff/cases/:ref', () => HttpResponse.json(caseView as object)),
    http.get('/api/bff/cases/:ref/options', ({ request }) => {
      optionsUrls.push(new URL(request.url).search);
      return HttpResponse.json(options as object);
    }),
  );
}

beforeEach(() => {
  resetCsrfCache();
  optionsUrls = [];
  answerWith(RADAR_VIEW);
});

describe('Radar: who covers this area (RadarWeb 1)', () => {
  it('reads the viewer’s own options only, and heads the page with the district', async () => {
    render(<RadarScreen caseId="4821" />);
    expect(await screen.findByRole('heading', { name: 'Who covers DT4 8XX' })).toBeInTheDocument();
    expect(optionsUrls).toEqual(['?only=own']);
    expect(screen.getByText('Visiting services show as areas. Hatched means two cover it. Places you go to show as icons.')).toBeInTheDocument();
  });

  it('says how many services cover the patient and offers the two next views', async () => {
    render(<RadarScreen caseId="4821" />);
    expect(await screen.findByText('This patient is covered by 3 services. Their areas overlap here, so compare them.')).toBeInTheDocument();
    expect(byEl('RADAR-COMPARE-BTN')).toHaveAttribute('href', '/advisor/case/4821/compare');
    expect(byEl('RADAR-WAYS-BTN')).toHaveAttribute('href', '/advisor/case/4821/ways');
    const tabs = screen.getByRole('navigation', { name: 'Radar views' });
    expect(within(tabs).getByRole('link', { name: 'Who covers' })).toHaveAttribute('aria-current', 'page');
    expect(within(tabs).getByRole('link', { name: 'Back to the map' })).toHaveAttribute('href', '/advisor/case/4821/map');
  });

  it('the layer chips turn a layer off and on, and say the two layers with no data are not available', async () => {
    const user = userEvent.setup();
    const { container } = render(<RadarScreen caseId="4821" />);
    await screen.findByRole('heading', { name: 'Who covers DT4 8XX' });
    expect(container.querySelectorAll('circle[stroke-dasharray]')).toHaveLength(3);

    await user.click(byEl('RADAR-LAYER-VISITING'));
    expect(byEl('RADAR-LAYER-VISITING')).toHaveAttribute('aria-pressed', 'false');
    expect(container.querySelectorAll('circle[stroke-dasharray]')).toHaveLength(1);

    await user.click(byEl('RADAR-LAYER-HOME'));
    expect(container.querySelectorAll('circle[stroke-dasharray]')).toHaveLength(0);

    await user.click(byEl('RADAR-LAYER-VISITING'));
    expect(container.querySelectorAll('circle[stroke-dasharray]')).toHaveLength(2);

    expect(screen.getByRole('button', { name: 'Drive-time rings: not available yet' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Traffic: not available yet' })).toBeDisabled();
  });

  it('a failed read says so and offers to try again', async () => {
    const user = userEvent.setup();
    server.use(http.get('/api/bff/cases/:ref/options', () => HttpResponse.json({ code: 'exception' }, { status: 502 })));
    render(<RadarScreen caseId="4821" />);
    expect(await screen.findByRole('alert')).toHaveTextContent('The radar could not be read. Try again.');

    answerWith(RADAR_VIEW);
    await user.click(byEl('RADAR-RETRY-BTN'));
    expect(await screen.findByRole('heading', { name: 'Who covers DT4 8XX' })).toBeInTheDocument();
  });

  it('shows the postcode-not-found state with the districts to choose, not a radar', async () => {
    answerWith(RADAR_NOT_FOUND);
    render(<RadarScreen caseId="4821" />);
    expect(await screen.findByRole('heading', { name: 'We could not find that postcode' })).toBeInTheDocument();
    expect(byEl('ADV-DISTRICT-DT3')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: /Who covers/ })).toBeNull();
  });

  it('shows the outside-the-area state, which names next steps', async () => {
    answerWith(RADAR_OUT_OF_AREA);
    render(<RadarScreen caseId="4821" />);
    expect(await screen.findByRole('heading', { name: 'No service covers this area' })).toBeInTheDocument();
    expect(byEl('ADV-NOFIT-CLINICAL-BTN')).toBeInTheDocument();
  });

  it('shows the no-service-fits state, never an empty radar, when nothing meets the criteria', async () => {
    answerWith(RADAR_EMPTY);
    render(<RadarScreen caseId="4821" />);
    await waitFor(() => expect(byEl('ADV-NOFIT-CLINICAL-BTN')).toBeInTheDocument());
    expect(screen.queryByRole('heading', { name: /Who covers/ })).toBeNull();
  });

  it('has no axe violations', async () => {
    const { container } = render(<main><RadarScreen caseId="4821" /></main>);
    await screen.findByRole('heading', { name: 'Who covers DT4 8XX' });
    expect((await runAxe(container)).violations).toEqual([]);
  });
});

describe('Compare the covering services (RadarWeb 2)', () => {
  it('says it is shadow mode and does not pick one', async () => {
    render(<CompareScreen caseId="4821" />);
    expect(await screen.findByRole('heading', { name: 'Compare for this patient' })).toBeInTheDocument();
    const banner = byEl('RADAR-SHADOW');
    expect(banner).toHaveTextContent('Shadow mode');
    expect(banner).toHaveTextContent('It does not pick one. The advisor and the clinical need decide.');
    expect(screen.queryByText(/best|recommended|top choice|score/i)).toBeNull();
  });

  it('lines up the services that visit or stay remote, in the order sent, and not the places to go', async () => {
    render(<CompareScreen caseId="4821" />);
    const table = await screen.findByRole('table');
    const heads = within(table).getAllByRole('columnheader').map((head) => head.textContent);
    expect(heads).toEqual(['Measure', 'UCR West', 'UCR East', 'Hospital at home']);
    expect(within(table).queryByText('Community hospital · Ward B')).toBeNull();
  });

  it('shows each measure for each service from the options the back end sent', async () => {
    render(<CompareScreen caseId="4821" />);
    const table = await screen.findByRole('table');
    const row = (id: string) => table.querySelector<HTMLElement>(`[data-row="${id}"]`) as HTMLElement;
    expect(within(row('status')).getByText('Accepting')).toBeInTheDocument();
    expect(within(row('status')).getByText('Limited')).toBeInTheDocument();
    expect(within(row('status')).getByText('Over capacity')).toBeInTheDocument();
    expect(row('free')).toHaveTextContent('4 referrals in the next 2 hrs');
    expect(row('free')).toHaveTextContent('1 referral');
    expect(row('free')).toHaveTextContent('+2 over');
    expect(row('reach')).toHaveTextContent('About 25 to 35 min');
    expect(row('reach')).toHaveTextContent('Not recorded');
    expect(row('age')).toHaveTextContent('9 min');
    expect(row('age')).toHaveTextContent('31 min');
    expect(row('age')).toHaveTextContent('14 min');
  });

  it('says Not available, not zero, for the two figures that need a service’s round', async () => {
    render(<CompareScreen caseId="4821" />);
    const table = await screen.findByRole('table');
    for (const id of ['round', 'near']) {
      const cells = within(table.querySelector<HTMLElement>(`[data-row="${id}"]`) as HTMLElement).getAllByRole('cell');
      expect(cells.map((cell) => cell.textContent)).toEqual(['Not available', 'Not available', 'Not available']);
    }
  });

  it('has a request for each service, grouped with its name, and says a request is only a request', async () => {
    render(<CompareScreen caseId="4821" />);
    await screen.findByRole('table');
    for (const name of ['UCR West', 'UCR East', 'Hospital at home']) {
      const group = screen.getByRole('group', { name: `Request ${name}` });
      expect(within(group).getByRole('button', { name: 'Request booking' })).toBeInTheDocument();
    }
    expect(screen.getByText('A request is only a request. It is not booked until the service confirms.')).toBeInTheDocument();
  });

  it('“Why these numbers” opens the explanation and closes it again', async () => {
    const user = userEvent.setup();
    render(<CompareScreen caseId="4821" />);
    await screen.findByRole('table');
    expect(screen.queryByRole('list', { name: 'Why these numbers' })).toBeNull();
    await user.click(byEl('RADAR-WHY-BTN'));
    expect(screen.getByRole('list', { name: 'Why these numbers' })).toHaveTextContent('Overwatch does not hold that yet');
    await user.click(byEl('RADAR-WHY-BTN'));
    expect(screen.queryByRole('list', { name: 'Why these numbers' })).toBeNull();
  });

  it('with nothing that visits or stays remote, says so and points to the three ways', async () => {
    answerWith({ ...RADAR_VIEW, options: RADAR_VIEW.options.filter((option) => option.position !== null) });
    render(<CompareScreen caseId="4821" />);
    expect(await screen.findByText(/there is nothing to compare here/)).toBeInTheDocument();
    expect(screen.queryByRole('table')).toBeNull();
    expect(screen.getByRole('link', { name: 'Three ways to meet the need' })).toHaveAttribute('href', '/advisor/case/4821/ways');
  });

  it('has no axe violations', async () => {
    const { container } = render(<main><CompareScreen caseId="4821" /></main>);
    await screen.findByRole('table');
    expect((await runAxe(container)).violations).toEqual([]);
  });
});

describe('Three ways to meet the need (RadarWeb 6, RadarPhone 5)', () => {
  const laneTitles = () => screen.getAllByRole('heading', { level: 3 }).map((heading) => heading.textContent);

  it('has the case line and three lanes with each service and its status', async () => {
    render(<WaysScreen caseId="4821" />);
    expect(await screen.findByRole('heading', { name: 'Meeting this need' })).toBeInTheDocument();
    expect(byEl('ADV-CASE-SUMMARY')).toHaveTextContent('DT4 8XX');
    expect(laneTitles()).toEqual(['Comes to the patient', 'Remote', 'Goes to a place']);
    const comes = document.querySelector('[data-lane="comes"]') as HTMLElement;
    expect(within(comes).getAllByRole('listitem')).toHaveLength(2);
    expect(within(comes).getByText('UCR West')).toBeInTheDocument();
    expect(within(comes).getByText('About 25 to 35 min')).toBeInTheDocument();
    expect(within(document.querySelector('[data-lane="remote"]') as HTMLElement).getByText('Over capacity')).toBeInTheDocument();
    expect(within(document.querySelector('[data-lane="place"]') as HTMLElement).getByText(/35 to 50 min by road, 5 beds/)).toBeInTheDocument();
  });

  it('the answer to can the patient travel changes the order of the lanes and hides nothing', async () => {
    const user = userEvent.setup();
    render(<WaysScreen caseId="4821" />);
    await screen.findByRole('heading', { name: 'Meeting this need' });
    const services = () => screen.getAllByRole('listitem').filter((item) => item.dataset.el === 'RADAR-WAY-ROW').length;
    expect(services()).toBe(4);

    await user.click(byEl('RADAR-TRAVEL-YES'));
    expect(byEl('RADAR-TRAVEL-YES')).toHaveAttribute('aria-pressed', 'true');
    expect(laneTitles()).toEqual(['Goes to a place', 'Comes to the patient', 'Remote']);
    expect(services()).toBe(4);

    await user.click(byEl('RADAR-TRAVEL-HELP'));
    expect(byEl('RADAR-TRAVEL-YES')).toHaveAttribute('aria-pressed', 'false');
    expect(laneTitles()).toEqual(['Comes to the patient', 'Goes to a place', 'Remote']);

    // Pressing the chosen answer again takes the answer back: it is optional.
    await user.click(byEl('RADAR-TRAVEL-HELP'));
    expect(laneTitles()).toEqual(['Comes to the patient', 'Remote', 'Goes to a place']);
  });

  it('an empty lane says so, and the not-suitable services are listed with why', async () => {
    const user = userEvent.setup();
    answerWith({ ...RADAR_VIEW, options: RADAR_VIEW.options.filter((option) => option.category !== 'hospital-at-home-or-virtual-ward') });
    render(<WaysScreen caseId="4821" />);
    await screen.findByRole('heading', { name: 'Meeting this need' });
    expect(within(document.querySelector('[data-lane="remote"]') as HTMLElement).getByText('None for this patient.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '1 service not suitable, and why' }));
    expect(screen.getByText('Urgent treatment centre: Open until 20:00, not suited to this need')).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const { container } = render(<main><WaysScreen caseId="4821" /></main>);
    await screen.findByRole('heading', { name: 'Meeting this need' });
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
