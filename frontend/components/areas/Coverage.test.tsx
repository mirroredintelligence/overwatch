import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { resetCsrfCache } from '@/lib/advisor/browser';
import { runAxe } from '@/test/a11y';
import { byEl } from '@/test/el';
import { server } from '@/test/msw/server';
import { CoverageByTime } from './CoverageByTime';
import { CoverageForm } from './CoverageForm';

const VIEW = {
  window: 'all',
  districts: [
    { district: 'DT1', services: ['UCR West'] },
    { district: 'DT3', services: ['UCR West', 'UCR East'] },
    { district: 'DT4', services: ['UCR West', 'UCR East'] },
    { district: 'DT5', services: [] },
    { district: 'DT6', services: [] },
  ],
  uncovered: { count: 31, suppressed: false, days: 90 },
};

let windows: string[];

function serveCoverage(answer: (window: string) => Response | object = () => VIEW) {
  windows = [];
  server.use(
    http.get('/api/bff/planning/coverage', ({ request }) => {
      const window = new URL(request.url).searchParams.get('window') ?? '';
      windows.push(window);
      const result = answer(window);
      return result instanceof Response ? result : HttpResponse.json({ ...(result as object), window });
    }),
  );
}

describe('Coverage by time of day (RadarWeb 4)', () => {
  it('shows each district with who covers it, in words and not by colour alone', async () => {
    serveCoverage();
    render(<CoverageByTime />);
    const tiles = await screen.findByRole('list', { name: 'Districts and who covers them' });
    const items = within(tiles).getAllByRole('listitem');
    expect(items.map((item) => item.getAttribute('data-cover'))).toEqual(['one', 'many', 'many', 'none', 'none']);
    expect(items[0]).toHaveTextContent('DT1');
    expect(items[0]).toHaveTextContent('One service');
    expect(items[1]).toHaveTextContent('Two or more');
    expect(items[1]).toHaveTextContent('UCR West, UCR East');
    expect(items[3]).toHaveTextContent('No cover');
    expect(items[3]).toHaveTextContent('No visiting service');
  });

  it('explains the three tile states in a legend beside the heading', async () => {
    serveCoverage();
    render(<CoverageByTime />);
    await screen.findByRole('list', { name: 'Districts and who covers them' });
    const legend = screen.getByText('Which visiting services cover each district').parentElement;
    expect(legend).toHaveTextContent('No cover');
    expect(legend).toHaveTextContent('One service');
    expect(legend).toHaveTextContent('Two or more');
  });

  it('says which districts have no cover, which have two or more, and the referrals from uncovered areas', async () => {
    serveCoverage();
    render(<CoverageByTime />);
    await screen.findByRole('list', { name: 'Districts and who covers them' });
    expect(byEl('COV-NONE')).toHaveTextContent('DT5, DT6');
    expect(byEl('COV-MANY')).toHaveTextContent('DT3, DT4');
    expect(byEl('COV-REFERRALS')).toHaveTextContent('31');
    expect(screen.getByText('Referrals from uncovered areas, last 90 days')).toBeInTheDocument();
    expect(screen.getByText('Coverage is by postcode district. Demand comes from the decision log. Groups under 10 are hidden.')).toBeInTheDocument();
  });

  it('a withheld count reads “Fewer than 10”, never 0', async () => {
    serveCoverage(() => ({ ...VIEW, uncovered: { count: null, suppressed: true, days: 90 } }));
    render(<CoverageByTime />);
    await screen.findByRole('list', { name: 'Districts and who covers them' });
    expect(byEl('COV-REFERRALS')).toHaveTextContent('Fewer than 10');
  });

  it('reads the whole day first, and again for each time of day chosen', async () => {
    const user = userEvent.setup();
    serveCoverage((window) => (window === 'night' ? { ...VIEW, districts: [{ district: 'DT5', services: [] }] } : VIEW));
    render(<CoverageByTime />);
    await screen.findByRole('list', { name: 'Districts and who covers them' });
    expect(byEl('COV-WINDOW-ALL')).toHaveAttribute('aria-pressed', 'true');

    await user.click(byEl('COV-WINDOW-NIGHT'));
    expect(byEl('COV-WINDOW-NIGHT')).toHaveAttribute('aria-pressed', 'true');
    expect(byEl('COV-WINDOW-ALL')).toHaveAttribute('aria-pressed', 'false');
    await waitFor(() => expect(within(screen.getByRole('list', { name: 'Districts and who covers them' })).getAllByRole('listitem')).toHaveLength(1));
    expect(windows).toEqual(['all', 'night']);
    expect(screen.getByRole('button', { name: '00:00 to 06:00' })).toBeInTheDocument();
  });

  it('the time of day is a group named “Time of day”', async () => {
    serveCoverage();
    render(<CoverageByTime />);
    await screen.findByRole('list', { name: 'Districts and who covers them' });
    expect(screen.getByRole('group', { name: 'Time of day' })).toBeInTheDocument();
  });

  it('the side card names the time of day chosen', async () => {
    const user = userEvent.setup();
    serveCoverage();
    render(<CoverageByTime />);
    await screen.findByRole('list', { name: 'Districts and who covers them' });
    await user.click(byEl('COV-WINDOW-AFTERNOON'));
    expect(await screen.findByText('In 12:00 to 18:00')).toBeInTheDocument();
  });

  it('before a tile is opened, says how to open one', async () => {
    serveCoverage();
    render(<CoverageByTime />);
    await screen.findByRole('list', { name: 'Districts and who covers them' });
    expect(screen.getByText('Open a tile to see who covers it. It does not change what either service accepts.')).toBeInTheDocument();
  });

  it('a tile opens to say who covers its district, from the mouse and from the keyboard', async () => {
    const user = userEvent.setup();
    serveCoverage();
    render(<CoverageByTime />);
    await screen.findByRole('list', { name: 'Districts and who covers them' });

    await user.click(byEl('COV-TILE-DT4'));
    expect(byEl('COV-TILE-DT4')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText('Covered by UCR West and UCR East all day.')).toBeInTheDocument();

    byEl('COV-TILE-DT5').focus();
    await user.keyboard('{Enter}');
    expect(byEl('COV-TILE-DT5')).toHaveAttribute('aria-pressed', 'true');
    expect(byEl('COV-TILE-DT4')).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByText('No visiting service covers DT5 all day.')).toBeInTheDocument();
  });

  it('a failed read says so and offers to try again', async () => {
    const user = userEvent.setup();
    serveCoverage(() => HttpResponse.json({ code: 'exception' }, { status: 404 }));
    render(<CoverageByTime />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Coverage by time of day could not be loaded. Try again.');
    serveCoverage();
    await user.click(byEl('COV-RETRY-BTN'));
    expect(await screen.findByRole('list', { name: 'Districts and who covers them' })).toBeInTheDocument();
  });

  it('an answer with no districts is said, not drawn as an empty page', async () => {
    serveCoverage(() => ({ ...VIEW, districts: [] }));
    render(<CoverageByTime />);
    expect(await screen.findByText('No districts are listed for this part of the day.')).toBeInTheDocument();
  });

  it('links to the planning view', async () => {
    serveCoverage();
    render(<CoverageByTime />);
    expect(byEl('COV-PLANNING-BTN')).toHaveAttribute('href', '/planning/flows');
  });

  it('has no axe violations', async () => {
    serveCoverage();
    const { container } = render(<main><CoverageByTime /></main>);
    await screen.findByRole('list', { name: 'Districts and who covers them' });
    expect((await runAxe(container)).violations).toEqual([]);
  });
});

const FORM = {
  service: { id: 'svc-ucr-west', name: 'UCR West' },
  available: ['DT1', 'DT2', 'DT3', 'DT4', 'DT5', 'DT6'],
  districts: ['DT3', 'DT4'],
  responseHours: 2,
  days: ['mon', 'tue', 'wed', 'thu', 'fri'],
  others: [{ district: 'DT4', service: 'UCR East' }],
};

type Put = { body: unknown; key: string | null; csrf: string | null };
let puts: Put[];

function serveForm(read: object = FORM, save: (body: unknown) => Response = (body) => HttpResponse.json({ ...FORM, ...(body as object) })) {
  puts = [];
  server.use(
    http.get('/api/bff/lead/services/:id/coverage', () => HttpResponse.json(read)),
    http.put('/api/bff/lead/services/:id/coverage', async ({ request }) => {
      const body = (await request.json()) as unknown;
      puts.push({ body, key: request.headers.get('idempotency-key'), csrf: request.headers.get('x-csrf-token') });
      return save(body);
    }),
  );
}

beforeEach(() => {
  resetCsrfCache();
});

describe('Define a coverage area (RadarWeb 5)', () => {
  it('asks where the service goes, with the districts, hours and days it has now', async () => {
    serveForm();
    render(<CoverageForm serviceId="svc-ucr-west" />);
    expect(await screen.findByRole('heading', { name: 'Where does UCR West go?' })).toBeInTheDocument();
    expect(byEl('COV-DISTRICT-DT3')).toHaveAttribute('aria-pressed', 'true');
    expect(byEl('COV-DISTRICT-DT1')).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByLabelText(/Response target \(hours\)/)).toHaveValue('2');
    expect(byEl('COV-DAY-FRI')).toHaveAttribute('aria-pressed', 'true');
    expect(byEl('COV-DAY-SAT')).toHaveAttribute('aria-pressed', 'false');
  });

  it('says how many of the districts on offer are chosen, and follows the choice', async () => {
    const user = userEvent.setup();
    serveForm();
    render(<CoverageForm serviceId="svc-ucr-west" />);
    expect(await screen.findByText('2 of 6 districts chosen')).toBeInTheDocument();
    await user.click(byEl('COV-DISTRICT-DT1'));
    expect(screen.getByText('3 of 6 districts chosen')).toBeInTheDocument();
  });

  it('shows how advisors will see the service, and follows the choice', async () => {
    const user = userEvent.setup();
    serveForm();
    render(<CoverageForm serviceId="svc-ucr-west" />);
    await screen.findByRole('heading', { name: 'Where does UCR West go?' });
    expect(screen.getByRole('heading', { name: 'How advisors will see it' })).toBeInTheDocument();
    expect(screen.getByText('Visits DT3 and DT4, Monday to Friday.')).toBeInTheDocument();
    expect(screen.getByText('Responds within about 2 hrs.')).toBeInTheDocument();

    await user.click(byEl('COV-DISTRICT-DT1'));
    expect(screen.getByText('Visits DT1, DT3 and DT4, Monday to Friday.')).toBeInTheDocument();
  });

  it('says which district the service will not be offered to, and which it will be offered with the other service', async () => {
    serveForm();
    render(<CoverageForm serviceId="svc-ucr-west" />);
    await screen.findByRole('heading', { name: 'Where does UCR West go?' });
    expect(screen.getByText('A patient in DT1 will not be offered this service.')).toBeInTheDocument();
    expect(screen.getByText('A patient in DT4 will be offered this one and UCR East.')).toBeInTheDocument();
  });

  it('names the other services that cover a chosen district, and follows the choice', async () => {
    const user = userEvent.setup();
    serveForm();
    render(<CoverageForm serviceId="svc-ucr-west" />);
    await screen.findByRole('heading', { name: 'Where does UCR West go?' });
    expect(byEl('COV-OVERLAP')).toHaveTextContent('Overlap. UCR East also covers DT4. Advisors will see both and compare them.');

    await user.click(byEl('COV-DISTRICT-DT4'));
    expect(document.querySelector('[data-el="COV-OVERLAP"]')).toBeNull();
    await user.click(byEl('COV-DISTRICT-DT4'));
    expect(byEl('COV-OVERLAP')).toBeInTheDocument();
  });

  it('the overlap note sits in a polite status, so a change of district is announced', async () => {
    serveForm();
    render(<CoverageForm serviceId="svc-ucr-west" />);
    await screen.findByRole('heading', { name: 'Where does UCR West go?' });
    expect(byEl('COV-OVERLAP').closest('[role="status"]')).not.toBeNull();
  });

  it('says the coverage area is loading while it is read', async () => {
    serveForm();
    render(<CoverageForm serviceId="svc-ucr-west" />);
    expect(screen.getByRole('status')).toHaveTextContent('Loading the coverage area.');
    await screen.findByRole('heading', { name: 'Where does UCR West go?' });
  });

  it('the save button names the coverage area it saves', async () => {
    serveForm();
    render(<CoverageForm serviceId="svc-ucr-west" />);
    await screen.findByRole('heading', { name: 'Where does UCR West go?' });
    expect(screen.getByRole('button', { name: 'Save the coverage area' })).toBeInTheDocument();
  });

  it('saves the three answers once, with the key and the CSRF token, and says it is saved', async () => {
    const user = userEvent.setup();
    server.use(http.get('/api/bff/session', () => HttpResponse.json({ csrfToken: 'csrf-for-the-form' })));
    serveForm();
    render(<CoverageForm serviceId="svc-ucr-west" />);
    await screen.findByRole('heading', { name: 'Where does UCR West go?' });

    await user.click(byEl('COV-DISTRICT-DT1'));
    await user.clear(screen.getByLabelText(/Response target \(hours\)/));
    await user.type(screen.getByLabelText(/Response target \(hours\)/), '4');
    await user.click(byEl('COV-DAY-SAT'));
    await user.click(byEl('COV-SAVE-BTN'));

    expect(await screen.findByText('The coverage area is saved.')).toBeInTheDocument();
    expect(puts).toHaveLength(1);
    expect(puts[0].body).toEqual({ districts: ['DT3', 'DT4', 'DT1'], responseHours: 4, days: ['mon', 'tue', 'wed', 'thu', 'fri', 'sat'] });
    expect(puts[0].key).toMatch(/^[A-Za-z0-9_-]{8,64}$/);
    expect(puts[0].csrf).toBe('csrf-for-the-form');
  });

  it('an incomplete form is not sent: a summary names each problem, and focus goes to it', async () => {
    const user = userEvent.setup();
    serveForm({ ...FORM, districts: [], responseHours: null, days: [] });
    render(<CoverageForm serviceId="svc-ucr-west" />);
    await screen.findByRole('heading', { name: 'Where does UCR West go?' });

    await user.click(byEl('COV-SAVE-BTN'));

    const summary = await screen.findByRole('alert');
    expect(summary).toHaveTextContent('There are 3 problems');
    expect(within(summary).getByText('Choose at least one district.')).toBeInTheDocument();
    expect(within(summary).getByText('Enter the response target in whole hours, from 1 to 72.')).toBeInTheDocument();
    expect(within(summary).getByText('Choose at least one day you visit.')).toBeInTheDocument();
    expect(puts).toHaveLength(0);
    await waitFor(() => expect(summary).toHaveFocus());
  });

  it('a save the back end refuses is said, and the form keeps what was typed', async () => {
    const user = userEvent.setup();
    serveForm(FORM, () => HttpResponse.json({ code: 'exception' }, { status: 500 }));
    render(<CoverageForm serviceId="svc-ucr-west" />);
    await screen.findByRole('heading', { name: 'Where does UCR West go?' });
    await user.click(byEl('COV-DISTRICT-DT1'));
    await user.click(byEl('COV-SAVE-BTN'));
    expect(await screen.findByText('The coverage area could not be saved. Try again.')).toBeInTheDocument();
    expect(byEl('COV-DISTRICT-DT1')).toHaveAttribute('aria-pressed', 'true');
  });

  it('a service with no coverage area on the back end yet says so, and offers a way back', async () => {
    server.use(http.get('/api/bff/lead/services/:id/coverage', () => HttpResponse.json({ code: 'not-found' }, { status: 404 })));
    render(<CoverageForm serviceId="svc-ucr-west" />);
    expect(await screen.findByRole('alert')).toHaveTextContent('The coverage area is not available for this service yet.');
    expect(screen.getByRole('link', { name: 'Back' })).toHaveAttribute('href', '/lead');
  });

  it('a read that fails says so and tries again on request', async () => {
    const user = userEvent.setup();
    serveForm();
    server.use(http.get('/api/bff/lead/services/:id/coverage', () => HttpResponse.json({ code: 'exception' }, { status: 502 }), { once: true }));
    render(<CoverageForm serviceId="svc-ucr-west" />);
    expect(await screen.findByRole('alert')).toHaveTextContent('could not be read');
    await user.click(byEl('COV-RETRY-BTN'));
    expect(await screen.findByRole('heading', { name: 'Where does UCR West go?' })).toBeInTheDocument();
  });

  it('has no axe violations, with and without the error summary', async () => {
    const user = userEvent.setup();
    serveForm({ ...FORM, districts: [] });
    const { container } = render(<CoverageForm serviceId="svc-ucr-west" />);
    await screen.findByRole('heading', { name: 'Where does UCR West go?' });
    expect((await runAxe(container)).violations).toEqual([]);
    await user.click(byEl('COV-SAVE-BTN'));
    await screen.findByRole('alert');
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
