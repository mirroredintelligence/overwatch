import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { resetCsrfCache } from '@/lib/advisor/browser';
import { MAP_VIEW } from '@/test/fixtures/map';
import { OPTIONS_VIEW } from '@/test/fixtures/options';
import { server } from '@/test/msw/server';
import { MapScreen } from './MapScreen';
import { OptionsList } from './OptionsList';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

// Choosing a district from the chips (W50, W9H DEC-1045, DEC-1046), on the map and on the list. The
// advisor presses a district; it is saved on the case by the BFF (one PUT with the key made for this
// press, the CSRF token of the session); the options are then read again and the screen shows what they
// say now. A choice that cannot be saved is said, and the options are not read again.

const CASE = { id: '4821', referrerType: 'gp', ageBand: '80+', postcode: 'ZZ9', needs: ['frailty'], urgency: 'within-2-hrs', scores: [], openedAt: null, etag: null };
const FLAGGED = { shownAt: OPTIONS_VIEW.shownAt, options: [], notSuitable: [], patientArea: null, notFound: true, outOfArea: false, districts: ['DT1', 'DT3'] };
const FOUND = { ...MAP_VIEW, notFound: false, outOfArea: false, districts: [] };
const OUT_OF_AREA = { ...FLAGGED, notFound: false, outOfArea: true, districts: ['DT2'] };

type Chosen = { body: unknown; key: string | null; csrf: string | null };
let reads: number;
let chosen: Chosen[];

function serve(first: object, then: object = OPTIONS_VIEW, save: () => Response = () => HttpResponse.json(CASE)) {
  reads = 0;
  chosen = [];
  server.use(
    http.get('/api/bff/cases/:ref', () => HttpResponse.json(CASE)),
    http.get('/api/bff/cases/:ref/options', () => {
      reads += 1;
      return HttpResponse.json(reads === 1 ? first : then);
    }),
    http.put('/api/bff/cases/:ref/district', async ({ request }) => {
      chosen.push({ body: await request.json(), key: request.headers.get('idempotency-key'), csrf: request.headers.get('x-csrf-token') });
      return save();
    }),
  );
}

beforeEach(() => {
  resetCsrfCache();
});

describe('choosing a district on the map', () => {
  it('offers the districts as their own card: pick one, then the one primary button says which it will use (MapLost)', async () => {
    serve(FLAGGED, FOUND);
    render(<MapScreen caseId="4821" />);

    const card = await screen.findByRole('region', { name: 'We could not place that postcode in your area' });
    // The case here is not complete, so there is no postcode field to say "Or" after.
    const group = within(card).getByRole('group', { name: 'Choose a district the services cover' });
    expect(within(group).getAllByRole('button').map((chip) => chip.textContent)).toEqual(['DT1', 'DT3']);
    expect(within(card).getByText('These are the districts at least one service covers.')).toBeInTheDocument();
    // Nothing is chosen for the advisor: the button waits.
    const use = within(card).getByRole('button', { name: 'Use district' });
    expect(use).toBeDisabled();

    await userEvent.click(within(group).getByRole('button', { name: 'DT3' }));

    expect(within(group).getByRole('button', { name: 'DT3' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(group).getByRole('button', { name: 'DT1' })).toHaveAttribute('aria-pressed', 'false');
    expect(within(card).getByRole('button', { name: 'Use district DT3' })).toBeEnabled();
    expect(within(card).getByText('The district is saved on the case and the options are read again.')).toBeInTheDocument();
    expect(within(card).getByRole('link', { name: 'Back to the list' })).toHaveAttribute('href', '/advisor/case/4821/options');
    expect(chosen).toHaveLength(0);
  });

  it('saves the district chosen with this press’s key and the session’s token, then reads the options again and shows the map', async () => {
    serve(FLAGGED, FOUND);
    render(<MapScreen caseId="4821" />);

    await userEvent.click(await screen.findByRole('button', { name: 'DT3' }));
    await userEvent.click(screen.getByRole('button', { name: 'Use district DT3' }));

    expect(await screen.findByRole('heading', { name: /Options near/ })).toBeInTheDocument();
    expect(chosen).toHaveLength(1);
    expect(chosen[0]?.body).toEqual({ district: 'DT3' });
    expect(chosen[0]?.key).toMatch(/^[\w-]{8,64}$/);
    expect(chosen[0]?.csrf).toBeTruthy();
    expect(reads).toBe(2);
  });

  it('reads the options again for the area no service covers too', async () => {
    serve(OUT_OF_AREA, FOUND);
    render(<MapScreen caseId="4821" />);

    await userEvent.click(await screen.findByRole('button', { name: 'DT2' }));

    await waitFor(() => expect(reads).toBe(2));
    expect(chosen[0]?.body).toEqual({ district: 'DT2' });
  });

  it('says so and does not read the options again when the district could not be saved', async () => {
    serve(FLAGGED, OPTIONS_VIEW, () => HttpResponse.json({ code: 'exception' }, { status: 502 }));
    render(<MapScreen caseId="4821" />);

    await userEvent.click(await screen.findByRole('button', { name: 'DT1' }));
    await userEvent.click(screen.getByRole('button', { name: 'Use district DT1' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('We could not use that district. Try again, or choose another.');
    expect(reads).toBe(1);
    expect(screen.getByRole('heading', { name: 'We could not place that postcode in your area' })).toBeInTheDocument();
  });

  it('says the case changed when another save came first (412), and offers the chips again', async () => {
    serve(FLAGGED, OPTIONS_VIEW, () => HttpResponse.json({ code: 'conflict' }, { status: 412 }));
    render(<MapScreen caseId="4821" />);

    await userEvent.click(await screen.findByRole('button', { name: 'DT1' }));
    await userEvent.click(screen.getByRole('button', { name: 'Use district DT1' }));

    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'DT1' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Use district DT1' })).toBeEnabled();
  });
});

describe('choosing a district on the list', () => {
  it('shows the postcode state with the chips, not the no-fit state, when nothing fits because of the postcode', async () => {
    serve(FLAGGED);
    render(<OptionsList caseId="4821" />);

    expect(await screen.findByRole('heading', { name: 'We could not find that postcode' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'DT1' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'No service fits right now' })).not.toBeInTheDocument();
  });

  it('shows the area state with the chips for a district no service covers', async () => {
    serve(OUT_OF_AREA);
    render(<OptionsList caseId="4821" />);

    expect(await screen.findByRole('heading', { name: 'No service covers this area' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'DT2' })).toBeInTheDocument();
  });

  it('saves the district and shows the options the list now has', async () => {
    serve(FLAGGED);
    render(<OptionsList caseId="4821" />);

    await userEvent.click(await screen.findByRole('button', { name: 'DT1' }));

    expect(await screen.findByRole('heading', { name: "3 services meet this patient's criteria" })).toBeInTheDocument();
    expect(chosen[0]?.body).toEqual({ district: 'DT1' });
    expect(reads).toBe(2);
    // The rows of the list the choice produced open the Request state, like any other list.
    expect(screen.getAllByRole('link', { name: /^Open / })).toHaveLength(3);
    expect(screen.queryByRole('button', { name: 'DT1' })).toBeNull();
  });

  it('shows the list, not the Request state, for a service id that the district choice made unavailable', async () => {
    serve(FLAGGED);
    render(<OptionsList caseId="4821" serviceId="svc-gone" />);

    await userEvent.click(await screen.findByRole('button', { name: 'DT1' }));

    expect(await screen.findByRole('heading', { name: "3 services meet this patient's criteria" })).toBeInTheDocument();
    expect(screen.queryByRole('complementary', { name: 'Other options' })).toBeNull();
  });

  it('keeps the list as it was when the postcode was not found but options exist (no travel times)', async () => {
    serve({ ...OPTIONS_VIEW, notFound: true, districts: ['DT1'] });
    render(<OptionsList caseId="4821" />);

    expect(await screen.findByRole('heading', { name: "3 services meet this patient's criteria" })).toBeInTheDocument();
  });
});
