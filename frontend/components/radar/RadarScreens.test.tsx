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

const views = () => screen.getByRole('navigation', { name: 'Options view' });

describe('Radar: who covers this area (RadarWeb 1)', () => {
  it('reads the viewer’s own options only, and heads the page with the district', async () => {
    render(<RadarScreen caseId="4821" />);
    expect(await screen.findByRole('heading', { name: 'Who covers DT4 8XX' })).toBeInTheDocument();
    expect(optionsUrls).toEqual(['?only=own']);
    expect(screen.getByText('Who covers DT4 8XX · the patient is shown at the postcode centre')).toBeInTheDocument();
  });

  it('shows the shared view toggle with Radar current, and no tabs of its own', async () => {
    render(<RadarScreen caseId="4821" />);
    await screen.findByRole('heading', { name: 'Who covers DT4 8XX' });
    expect(within(views()).getByRole('link', { name: 'Radar' })).toHaveAttribute('aria-current', 'page');
    expect(within(views()).getByRole('link', { name: 'Compare' })).toHaveAttribute('href', '/advisor/case/4821/compare');
    expect(within(views()).getByRole('link', { name: 'Ways' })).toHaveAttribute('href', '/advisor/case/4821/ways');
    expect(within(views()).getByRole('link', { name: 'Map' })).toHaveAttribute('href', '/advisor/case/4821/map');
    expect(screen.queryByRole('navigation', { name: 'Radar views' })).toBeNull();
  });

  it('has a key that names each visiting service, the hatching, the places and the two layers that are off', async () => {
    render(<RadarScreen caseId="4821" />);
    await screen.findByRole('heading', { name: 'Who covers DT4 8XX' });
    const key = within(screen.getByRole('region', { name: 'Key and services' }));
    expect(key.getByText('UCR West visits this area')).toBeInTheDocument();
    expect(key.getByText('UCR East visits this area')).toBeInTheDocument();
    expect(key.getByText('Hospital at home visits this area')).toBeInTheDocument();
    expect(key.getByText('Both visit: hatched')).toBeInTheDocument();
    expect(key.getByText('A place to go to')).toBeInTheDocument();
    expect(key.getByText('Drive-time rings: off, no data yet')).toBeInTheDocument();
    expect(byEl('RADAR-OFF-NOTE')).toHaveTextContent('Drive-time rings and traffic are off');
  });

  it('lists who covers the district with each status and figure, and says how many cover the patient', async () => {
    render(<RadarScreen caseId="4821" />);
    await screen.findByRole('heading', { name: 'Who covers DT4 8XX' });
    const covering = within(byEl('RADAR-COVERING'));
    expect(covering.getByRole('heading', { name: 'Covering DT4 8XX' })).toBeInTheDocument();
    expect(covering.getByText('Accepting · 4')).toBeInTheDocument();
    expect(covering.getByText('Limited · 1')).toBeInTheDocument();
    expect(covering.getByText('Over capacity · +2')).toBeInTheDocument();
    expect(byEl('RADAR-SUMMARY')).toHaveTextContent('This patient is covered by 3 services. Their areas overlap here, so compare them.');
  });

  it('draws every area, since there are no layers to turn off', async () => {
    const { container } = render(<RadarScreen caseId="4821" />);
    await screen.findByRole('heading', { name: 'Who covers DT4 8XX' });
    expect(container.querySelectorAll('[data-el^="RADAR-AREA-"]')).toHaveLength(3);
    expect(screen.queryByRole('group', { name: 'Layers' })).toBeNull();
    expect(screen.queryByRole('button', { name: /not available yet/ })).toBeNull();
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
    expect(within(views()).getByRole('link', { name: 'Radar' })).toHaveAttribute('aria-current', 'page');
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
  it('has the patient card, the shared view toggle with Compare current, and how many services are lined up', async () => {
    render(<CompareScreen caseId="4821" />);
    expect(await screen.findByRole('heading', { name: 'Compare for this patient' })).toBeInTheDocument();
    expect(byEl('ADV-CASE-SUMMARY')).toHaveTextContent('DT4 8XX');
    expect(byEl('ADV-CASE-SUMMARY-EDIT')).toHaveAttribute('href', '/advisor/case/4821');
    expect(within(views()).getByRole('link', { name: 'Compare' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByText('3 services meet the criteria · same order as the list')).toBeInTheDocument();
    expect(screen.queryByRole('navigation', { name: 'Radar views' })).toBeNull();
  });

  it('does not pick one: no score, no rank and no best mark, said once under the table', async () => {
    render(<CompareScreen caseId="4821" />);
    const table = await screen.findByRole('table');
    const note = byEl('RADAR-SHADOW');
    expect(note).toHaveTextContent('It does not pick one: there is no score, no rank and no best mark.');
    expect(note).toHaveTextContent('The advisor and the clinical need decide.');
    expect(note).toHaveTextContent('A request is only a request, and is not booked until the service confirms.');
    expect(note).toHaveTextContent('Rows that need a service’s round say Not available, which is not zero.');
    expect(within(table).queryByText(/best|recommended|top choice|score|rank/i)).toBeNull();
    expect(screen.queryByText('Shadow mode')).toBeNull();
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

  it('has the same outlined request for each service, grouped with its name, so no column looks recommended', async () => {
    render(<CompareScreen caseId="4821" />);
    await screen.findByRole('table');
    const requests = new Set<string>();
    for (const name of ['UCR West', 'UCR East', 'Hospital at home']) {
      const group = screen.getByRole('group', { name: `Request ${name}` });
      const button = within(group).getByRole('button', { name: 'Request booking' });
      requests.add(button.className);
      expect(group.closest('td')).toHaveAttribute('data-request', 'outlined');
    }
    // One style for every column.
    expect(requests.size).toBe(1);
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
  const lane = (id: string) => document.querySelector(`[data-lane="${id}"]`) as HTMLElement;

  it('has the shared view toggle with Ways current, the case line and three lanes with each service and its status', async () => {
    render(<WaysScreen caseId="4821" />);
    expect(await screen.findByRole('heading', { name: 'Meeting this need' })).toBeInTheDocument();
    expect(within(views()).getByRole('link', { name: 'Ways' })).toHaveAttribute('aria-current', 'page');
    expect(byEl('ADV-CASE-SUMMARY')).toHaveTextContent('DT4 8XX');
    expect(laneTitles()).toEqual(['Comes to the patient', 'Remote', 'Goes to a place']);
    expect(within(lane('comes')).getAllByRole('listitem')).toHaveLength(2);
    const west = within(lane('comes')).getAllByRole('listitem')[0];
    expect(west).toHaveTextContent('UCR West');
    expect(west).toHaveTextContent('Visits about 25 to 35 min · 9 min ago');
    expect(west).toHaveTextContent('Accepting');
    expect(west).toHaveTextContent('4 referrals in the next 2 hrs');
    const home = within(lane('remote')).getAllByRole('listitem')[0];
    expect(home).toHaveTextContent('Over capacity');
    expect(home).toHaveTextContent('+2 over');
    expect(home).toHaveTextContent('Phone to confirm before offering.');
    const place = within(lane('place')).getAllByRole('listitem')[0];
    expect(place).toHaveTextContent('About 35 to 50 min by road');
    expect(place).toHaveTextContent('· old');
    expect(place).toHaveTextContent('5 beds free');
  });

  it('each service has an Open link named for it', async () => {
    render(<WaysScreen caseId="4821" />);
    await screen.findByRole('heading', { name: 'Meeting this need' });
    expect(screen.getByRole('link', { name: 'Open UCR West' })).toHaveAttribute('href', '/advisor/case/4821/options?service=svc-ucr-west');
    expect(screen.getAllByRole('link', { name: /^Open / })).toHaveLength(4);
  });

  it('the answer to can the patient travel changes the order of the lanes and hides nothing', async () => {
    const user = userEvent.setup();
    render(<WaysScreen caseId="4821" />);
    await screen.findByRole('heading', { name: 'Meeting this need' });
    expect(screen.getByText('This only changes which way is shown first. It never hides a way or a service.')).toBeInTheDocument();
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

  it('an empty lane says so, and the services left out are listed with why', async () => {
    const user = userEvent.setup();
    answerWith({ ...RADAR_VIEW, options: RADAR_VIEW.options.filter((option) => option.category !== 'hospital-at-home-or-virtual-ward') });
    render(<WaysScreen caseId="4821" />);
    await screen.findByRole('heading', { name: 'Meeting this need' });
    expect(within(lane('remote')).getByText('None for this patient.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '1 service not suitable, and why' }));
    expect(screen.getByText('Urgent treatment centre: Open until 20:00, not suited to this need')).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const { container } = render(<main><WaysScreen caseId="4821" /></main>);
    await screen.findByRole('heading', { name: 'Meeting this need' });
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
