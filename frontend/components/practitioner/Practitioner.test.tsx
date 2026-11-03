import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { OFFER_SAMPLE, resetPractitionerRequests, seenPractitionerRequests, SHIFT_SAMPLE, VISIT_SAMPLE } from '@/test/msw/handlers/practitioner';
import { server } from '@/test/msw/server';
import { greeting, ShiftScreen } from './ShiftScreen';
import { LocationScreen } from './LocationScreen';
import { RoundScreen } from './RoundScreen';
import { VisitLoader } from './VisitScreens';

vi.setConfig({ testTimeout: 20_000 });

const { push, replace } = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace }) }));

beforeEach(() => {
  push.mockClear();
  replace.mockClear();
  resetPractitionerRequests();
});
afterEach(() => vi.useRealTimers());

const sent = (method: string, path: string) => seenPractitionerRequests.find((r) => r.method === method && r.path === path);

describe('My shift (RadarPhone 1)', () => {
  it('shows the greeting, the optional status, today’s visits and the next one, and the note about location', async () => {
    const { container } = render(<ShiftScreen />);
    expect(await screen.findByRole('heading', { level: 1 })).toHaveTextContent(/^Good (morning|afternoon|evening)$/);
    expect(screen.getByText('Optional')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Available' })).toHaveAttribute('aria-pressed', 'true');
    for (const word of ['On a visit', 'Break', 'Off shift']) expect(screen.getByRole('button', { name: word })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByText('Today: 4 visits')).toBeInTheDocument();
    expect(screen.getByText(/^Next: \d\d:\d\d, sector DT4 8$/)).toBeInTheDocument();
    expect(screen.getByText('Your location is not shared unless you turn it on for a visit.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'See today’s round' })).toHaveAttribute('href', '/app/practitioner/round');
    expect(screen.getByRole('link', { name: 'Share location during visits' })).toHaveAttribute('href', '/app/practitioner/location');
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('shows a shimmer while it opens, and says so in words', async () => {
    const { container } = render(<ShiftScreen />);
    const status = screen.getByRole('status');
    expect(status).toHaveTextContent('Opening your shift.');
    expect(status).toHaveAttribute('aria-busy', 'true');
    expect(container.querySelector('[data-skeleton]')).not.toBeNull();
    await screen.findByRole('heading', { level: 1 });
  });

  it('lists an offer waiting as a card with a tag, the need and the sector, and no address', async () => {
    const { container } = render(<ShiftScreen />);
    const link = await screen.findByRole('link', { name: /Fall, no injury/ });
    expect(link).toHaveAttribute('href', '/app/practitioner/offers/offer-1');
    expect(link).toHaveTextContent('1 new offer');
    expect(link).toHaveTextContent('Sector DT4 8 · within 2 hrs');
    expect(link.querySelector('[data-variant="live"]')).not.toBeNull();
    expect(container.textContent).not.toMatch(/street|07\d{3}|postcode/i);
  });

  it('counts the offers when there is more than one, and tags each as new', async () => {
    const second = { id: 'offer-2', need: 'Wound check', sector: 'DT1 2', wantedWithin: 'planned', expiresAt: '2026-10-31T14:50:00Z' };
    server.use(http.get('/api/bff/practitioner/shift', () => HttpResponse.json({ ...SHIFT_SAMPLE, offers: [...SHIFT_SAMPLE.offers, second] })));
    render(<ShiftScreen />);
    expect(await screen.findByText('2 new offers')).toBeInTheDocument();
    expect(screen.getAllByText('New offer')).toHaveLength(2);
    expect(screen.getByRole('link', { name: /Wound check/ })).toHaveTextContent('Sector DT1 2 · planned visit');
  });

  it('says what the location choice is, when it is to share while travelling', async () => {
    server.use(http.get('/api/bff/practitioner/shift', () => HttpResponse.json({ ...SHIFT_SAMPLE, location: 'travel' })));
    render(<ShiftScreen />);
    expect(await screen.findByText('You share an estimated arrival, only while you travel to a visit.')).toBeInTheDocument();
  });

  it('sets a status with one press, and clears it with another', async () => {
    render(<ShiftScreen />);
    await userEvent.click(await screen.findByRole('button', { name: 'Break' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Break' })).toHaveAttribute('aria-pressed', 'true'));
    expect(sent('PUT', '/api/bff/practitioner/settings')?.body).toEqual({ status: 'break' });
    expect(screen.getByRole('button', { name: 'Available' })).toHaveAttribute('aria-pressed', 'false');
    await userEvent.click(screen.getByRole('button', { name: 'Break' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Break' })).toHaveAttribute('aria-pressed', 'false'));
    expect(seenPractitionerRequests.filter((r) => r.method === 'PUT').at(-1)?.body).toEqual({ status: null });
  });

  it('says so when a status could not be saved, and keeps the old one', async () => {
    server.use(http.put('/api/bff/practitioner/settings', () => HttpResponse.json({ code: 'exception' }, { status: 502 })));
    render(<ShiftScreen />);
    await userEvent.click(await screen.findByRole('button', { name: 'Break' }));
    expect(await screen.findByText('We could not save that. Try again.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Available' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('says there are no visits when there are none, and has no status pressed when none is set', async () => {
    server.use(http.get('/api/bff/practitioner/shift', () => HttpResponse.json({ ...SHIFT_SAMPLE, status: null, visitsToday: 0, next: null, offers: [], round: [] })));
    render(<ShiftScreen />);
    expect(await screen.findByText('Today: no visits yet')).toBeInTheDocument();
    for (const word of ['Available', 'On a visit', 'Break', 'Off shift']) expect(screen.getByRole('button', { name: word })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.queryByText(/new offer/)).not.toBeInTheDocument();
  });

  it('names the next visit by its sector and when it is wanted when it has no time', async () => {
    server.use(http.get('/api/bff/practitioner/shift', () => HttpResponse.json({ ...SHIFT_SAMPLE, next: { ...SHIFT_SAMPLE.next, dueBy: null, wantedWithin: 'today' } })));
    render(<ShiftScreen />);
    expect(await screen.findByText('Next: sector DT4 8, today')).toBeInTheDocument();
  });

  it('goes to the PIN screen when the session has ended', async () => {
    server.use(http.get('/api/bff/practitioner/shift', () => HttpResponse.json({ code: 'session-ended' }, { status: 401 })));
    render(<ShiftScreen />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/app/pin'));
  });

  it('shows a failure as a failure, not as an empty shift', async () => {
    server.use(http.get('/api/bff/practitioner/shift', () => HttpResponse.json({ nonsense: true })));
    render(<ShiftScreen />);
    expect(await screen.findByText('We could not load your shift. Try again shortly.')).toBeInTheDocument();
  });

  it('greets by the hour', () => {
    expect([greeting(6), greeting(11), greeting(12), greeting(17), greeting(18), greeting(23)]).toEqual(['Good morning', 'Good morning', 'Good afternoon', 'Good afternoon', 'Good evening', 'Good evening']);
  });
});

describe('Today’s round', () => {
  const ROUND = [
    { id: 'visit-1', sector: 'DT4 8', state: 'accepted', dueBy: '2026-10-31T14:30:00Z', wantedWithin: 'within 2 hrs' },
    { id: 'visit-3', sector: 'DT9 9', state: 'offered', dueBy: null, wantedWithin: 'today' },
    { id: 'visit-4', sector: 'DT2 1', state: 'accepted', dueBy: null, wantedWithin: 'planned' },
    { id: 'visit-2', sector: 'DT1 2', state: 'done', dueBy: null, wantedWithin: 'today' },
  ];

  it('shows the next visit first, then the later ones, each with a tag, in the order the back end gives', async () => {
    server.use(http.get('/api/bff/practitioner/shift', () => HttpResponse.json({ ...SHIFT_SAMPLE, round: ROUND })));
    const { container } = render(<RoundScreen />);
    const next = await screen.findByRole('list', { name: 'Next' });
    const nextRows = within(next).getAllByRole('link');
    expect(nextRows).toHaveLength(1);
    expect(nextRows[0]).toHaveAttribute('href', '/app/practitioner/visits/visit-1');
    expect(nextRows[0]).toHaveTextContent(/\d\d:\d\d · sector DT4 8.*Within 2 hrs.*Accepted/);
    const later = screen.getByRole('list', { name: 'Later' });
    const laterRows = within(later).getAllByRole('link');
    expect(laterRows).toHaveLength(2);
    expect(laterRows[0]).toHaveTextContent(/Sector DT9 9.*Today.*Offered/);
    expect(laterRows[1]).toHaveTextContent(/Sector DT2 1.*Planned.*Accepted/);
    expect(container.textContent).not.toMatch(/street|07\d{3}/i);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('keeps finished visits under a closed "Done today (n)" row that opens on request', async () => {
    server.use(http.get('/api/bff/practitioner/shift', () => HttpResponse.json({ ...SHIFT_SAMPLE, round: ROUND })));
    render(<RoundScreen />);
    const toggle = await screen.findByRole('button', { name: 'Done today (1)' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    const done = screen.getByRole('link', { name: /Sector DT1 2/ });
    expect(done).toHaveAttribute('href', '/app/practitioner/visits/visit-2');
    expect(done).toHaveTextContent(/Today.*Done/);
  });

  it('has no Later heading when only one visit is left, and no Done row when none is done', async () => {
    server.use(http.get('/api/bff/practitioner/shift', () => HttpResponse.json({ ...SHIFT_SAMPLE, round: [ROUND[0]] })));
    render(<RoundScreen />);
    await screen.findByRole('list', { name: 'Next' });
    expect(screen.queryByText('Later')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Done today/ })).not.toBeInTheDocument();
  });

  it('puts the finished visits in the Done row by their own words, and nothing in Next', async () => {
    const finished = [
      { id: 'v-a', sector: 'DT1 1', state: 'not-reached', dueBy: null, wantedWithin: 'today' },
      { id: 'v-b', sector: 'DT1 2', state: 'declined', dueBy: null, wantedWithin: 'today' },
    ];
    server.use(http.get('/api/bff/practitioner/shift', () => HttpResponse.json({ ...SHIFT_SAMPLE, round: finished })));
    render(<RoundScreen />);
    expect(await screen.findByRole('button', { name: 'Done today (2)' })).toBeInTheDocument();
    expect(screen.queryByRole('list', { name: 'Next' })).not.toBeInTheDocument();
    expect(screen.getByText('Nothing left to do today.')).toBeInTheDocument();
    expect(screen.getByText('Could not reach')).toBeInTheDocument();
    expect(screen.getByText('Declined')).toBeInTheDocument();
  });

  it('shows a shimmer while it opens', async () => {
    render(<RoundScreen />);
    expect(screen.getByRole('status')).toHaveTextContent('Opening your round.');
    await screen.findByRole('heading', { level: 1 });
  });

  it('says so when there are no visits', async () => {
    server.use(http.get('/api/bff/practitioner/shift', () => HttpResponse.json({ ...SHIFT_SAMPLE, round: [], visitsToday: 0, next: null })));
    render(<RoundScreen />);
    expect(await screen.findByText('No visits yet today.')).toBeInTheDocument();
  });
});

describe('Visit offer (RadarPhone 2)', () => {
  it('shows what is needed, the sector, when it is wanted, the countdown and that the address comes after accepting', async () => {
    const soon = new Date(Date.now() + 270_000).toISOString().replace(/\.\d{3}Z$/, 'Z');
    server.use(http.get('/api/bff/practitioner/visits/offer-1', () => HttpResponse.json({ ...OFFER_SAMPLE, expiresAt: soon })));
    const { container } = render(<VisitLoader id="offer-1" />);
    expect(await screen.findByText('New offer')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'Fall, no injury' })).toBeInTheDocument();
    const facts = container.querySelector('[data-el="PRAC-OFFER-FACTS"]') as HTMLElement;
    expect(facts).toHaveTextContent('Area DT4 8 (sector)');
    expect(facts).toHaveTextContent('Wanted within 2 hrs');
    expect(facts).toHaveTextContent(/Offer expires in 4:[23]\d/);
    expect(facts).not.toHaveTextContent('Fits your round');
    expect(screen.getByText('The address and contact appear only after you accept.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Accept visit' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Decline' })).toBeEnabled();
    expect(container.textContent).not.toMatch(/street|07\d{3}/i);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('shows how much the visit adds to the round only when the back end says', async () => {
    server.use(http.get('/api/bff/practitioner/visits/offer-1', () => HttpResponse.json({ ...OFFER_SAMPLE, fitsMinutes: 6 })));
    render(<VisitLoader id="offer-1" />);
    expect(await screen.findByText(/Fits your round:/)).toHaveTextContent('Fits your round: +6 min to your next visit');
  });

  it('counts down each second and becomes expired when the time is up', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const soon = new Date(Date.now() + 3_000).toISOString().replace(/\.\d{3}Z$/, 'Z');
    server.use(http.get('/api/bff/practitioner/visits/offer-1', () => HttpResponse.json({ ...OFFER_SAMPLE, expiresAt: soon })));
    render(<VisitLoader id="offer-1" />);
    expect(await screen.findByText('New offer')).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(await screen.findByRole('heading', { name: 'Offer expired' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Accept visit' })).not.toBeInTheDocument();
  });

  it('accepts once, with an Idempotency-Key, and goes to the accepted visit', async () => {
    render(<VisitLoader id="offer-1" />);
    await userEvent.click(await screen.findByRole('button', { name: 'Accept visit' }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/app/practitioner/visits/offer-1'));
    const call = sent('POST', '/api/bff/practitioner/visits/offer-1/accept');
    expect(call?.body).toEqual({});
    expect(call?.idempotencyKey).toMatch(/.{8,}/);
  });

  it('declines, and goes back to the shift', async () => {
    render(<VisitLoader id="offer-1" />);
    await userEvent.click(await screen.findByRole('button', { name: 'Decline' }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/app/practitioner'));
    expect(sent('POST', '/api/bff/practitioner/visits/offer-1/decline')?.idempotencyKey).toMatch(/.{8,}/);
  });

  it('disables both buttons while the answer is sent, so a second press sends nothing', async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => (release = resolve));
    server.use(
      http.post('/api/bff/practitioner/visits/offer-1/accept', async ({ request }) => {
        seenPractitionerRequests.push({ path: '/api/bff/practitioner/visits/offer-1/accept', method: 'POST', body: await request.json() });
        await gate;
        return HttpResponse.json({ id: 'offer-1', state: 'accepted' });
      }),
    );
    render(<VisitLoader id="offer-1" />);
    const accept = await screen.findByRole('button', { name: 'Accept visit' });
    await userEvent.click(accept);
    await waitFor(() => expect(accept).toBeDisabled());
    expect(screen.getByRole('button', { name: 'Decline' })).toBeDisabled();
    await userEvent.click(accept);
    release();
    await waitFor(() => expect(replace).toHaveBeenCalled());
    expect(seenPractitionerRequests.filter((r) => r.path.endsWith('/accept') && r.method === 'POST')).toHaveLength(1);
  });

  it('shows what the back end holds when a colleague took the visit first', async () => {
    let taken = false;
    server.use(
      http.get('/api/bff/practitioner/visits/offer-1', () => HttpResponse.json(taken ? { ...OFFER_SAMPLE, state: 'withdrawn' } : OFFER_SAMPLE)),
      http.post('/api/bff/practitioner/visits/offer-1/accept', () => {
        taken = true;
        return HttpResponse.json({ code: 'invalid' }, { status: 409 });
      }),
    );
    render(<VisitLoader id="offer-1" />);
    await userEvent.click(await screen.findByRole('button', { name: 'Accept visit' }));
    expect(await screen.findByRole('heading', { name: 'No longer open' })).toBeInTheDocument();
    expect(screen.getByText('This visit was taken by a colleague, or the booking was cancelled.')).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });

  it('says it could not send when the back end fails, and lets the person try again', async () => {
    server.use(http.post('/api/bff/practitioner/visits/offer-1/accept', () => HttpResponse.json({ code: 'exception' }, { status: 502 })));
    render(<VisitLoader id="offer-1" />);
    await userEvent.click(await screen.findByRole('button', { name: 'Accept visit' }));
    expect(await screen.findByText('We could not send that. Try again.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Accept visit' })).toBeEnabled();
  });

  it('shows a visit that is not the person’s as a failure to load, with nothing of it', async () => {
    const { container } = render(<VisitLoader id="nobody-1" />);
    expect(await screen.findByText('We could not load this visit. Try again shortly.')).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/street|DT4/i);
  });
});

describe('Visit accepted (RadarPhone 3)', () => {
  it('shows the address and contact to this person, the status list, and the way to maps', async () => {
    const { container } = render(<VisitLoader id="visit-1" />);
    expect(await screen.findByText('Accepted')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'Visit 4821' })).toBeInTheDocument();
    expect(screen.getByText('Address and contact now shown to you only.')).toBeInTheDocument();
    expect(screen.getByText('1 Synthetic Street')).toBeInTheDocument();
    expect(screen.getByText('Daughter, 07000 000000')).toBeInTheDocument();
    expect(screen.getByText('Wanted within 2 hrs.')).toBeInTheDocument();
    const list = screen.getByRole('group', { name: 'Visit status' });
    expect(within(list).getAllByRole('button').map((b) => b.textContent)).toEqual(['On my way', 'Arrived', 'Visit done', 'Could not reach the patient']);
    expect(screen.getByRole('link', { name: 'Open in maps' })).toHaveAttribute('href', 'geo:0,0?q=1%20Synthetic%20Street');
    expect(screen.getByRole('button', { name: 'Update status' })).toBeDisabled();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('shows no address when the back end sends none, and says whom to phone', async () => {
    const { address, contact, ...bare } = VISIT_SAMPLE;
    void address;
    void contact;
    server.use(http.get('/api/bff/practitioner/visits/visit-1', () => HttpResponse.json(bare)));
    render(<VisitLoader id="visit-1" />);
    expect(await screen.findByText('They could not be shown here. Phone the coordination team.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Open in maps' })).toBeDisabled();
  });

  it('drops the details when the back end sends only half of them', async () => {
    const { contact, ...half } = VISIT_SAMPLE;
    void contact;
    server.use(http.get('/api/bff/practitioner/visits/visit-1', () => HttpResponse.json(half)));
    const { container } = render(<VisitLoader id="visit-1" />);
    expect(await screen.findByText('They could not be shown here. Phone the coordination team.')).toBeInTheDocument();
    expect(container.textContent).not.toContain('Synthetic');
  });

  it('never shows details for an offer that is not accepted, even if the back end sent them', async () => {
    server.use(http.get('/api/bff/practitioner/visits/offer-1', () => HttpResponse.json({ ...OFFER_SAMPLE, address: '1 Synthetic Street', contact: 'Daughter' })));
    const { container } = render(<VisitLoader id="offer-1" />);
    expect(await screen.findByText('New offer')).toBeInTheDocument();
    expect(container.textContent).not.toContain('Synthetic');
  });

  it('sends the chosen status with an Idempotency-Key and says what was updated', async () => {
    render(<VisitLoader id="visit-1" />);
    await userEvent.click(await screen.findByRole('button', { name: 'Arrived' }));
    expect(screen.getByRole('button', { name: 'Arrived' })).toHaveAttribute('aria-pressed', 'true');
    await userEvent.click(screen.getByRole('button', { name: 'Update status' }));
    expect(await screen.findByText('Status updated: Arrived.')).toBeInTheDocument();
    const call = sent('POST', '/api/bff/practitioner/visits/visit-1/status');
    expect(call?.body).toEqual({ status: 'arrived' });
    expect(call?.idempotencyKey).toMatch(/.{8,}/);
  });

  it('offers an estimate only on the way and only when location sharing is on, and sends minutes, never a position', async () => {
    render(<VisitLoader id="visit-1" />);
    await userEvent.click(await screen.findByRole('button', { name: 'On my way' }));
    const group = screen.getByRole('group', { name: 'Estimated arrival' });
    expect(within(group).getByText('You choose the estimate. Your phone’s position is not sent.')).toBeInTheDocument();
    await userEvent.click(within(group).getByRole('button', { name: '20 min' }));
    await userEvent.click(screen.getByRole('button', { name: 'Update status' }));
    await screen.findByText('Status updated: On my way.');
    expect(sent('POST', '/api/bff/practitioner/visits/visit-1/status')?.body).toEqual({ status: 'on-my-way', etaMinutes: 20 });
  });

  it('offers no estimate when the location is never shared', async () => {
    server.use(http.get('/api/bff/practitioner/visits/visit-1', () => HttpResponse.json({ ...VISIT_SAMPLE, location: 'never' })));
    render(<VisitLoader id="visit-1" />);
    await userEvent.click(await screen.findByRole('button', { name: 'On my way' }));
    expect(screen.queryByRole('group', { name: 'Estimated arrival' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Update status' }));
    await screen.findByText('Status updated: On my way.');
    expect(sent('POST', '/api/bff/practitioner/visits/visit-1/status')?.body).toEqual({ status: 'on-my-way' });
  });

  it('shows the estimate the person gave, as a time', async () => {
    server.use(http.get('/api/bff/practitioner/visits/visit-1', () => HttpResponse.json({ ...VISIT_SAMPLE, state: 'on-my-way', etaAt: '2026-10-31T14:50:00Z' })));
    render(<VisitLoader id="visit-1" />);
    expect(await screen.findByText(/^Estimated arrival shared: \d\d:\d\d\.$/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'On my way' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('shows the closed page, with the details gone, once the visit is done', async () => {
    let done = false;
    server.use(
      http.get('/api/bff/practitioner/visits/visit-1', () => HttpResponse.json(done ? { ...OFFER_SAMPLE, id: 'visit-1', state: 'done' } : VISIT_SAMPLE)),
      http.post('/api/bff/practitioner/visits/visit-1/status', () => {
        done = true;
        return HttpResponse.json({ id: 'visit-1', state: 'done' });
      }),
    );
    const { container } = render(<VisitLoader id="visit-1" />);
    await userEvent.click(await screen.findByRole('button', { name: 'Visit done' }));
    await userEvent.click(screen.getByRole('button', { name: 'Update status' }));
    expect(await screen.findByRole('heading', { name: 'Visit done' })).toBeInTheDocument();
    expect(container.textContent).not.toContain('Synthetic');
    expect(screen.getByRole('link', { name: 'Back to my shift' })).toHaveAttribute('href', '/app/practitioner');
  });

  it('shows a closed visit as closed, with a way back', async () => {
    render(<VisitLoader id="gone-1" />);
    expect(await screen.findByRole('heading', { name: 'No longer open' })).toBeInTheDocument();
  });
});

describe('Location sharing (RadarPhone 4)', () => {
  it('asks the question with the two answers and the three reassurances, and starts as never', async () => {
    const { container } = render(<LocationScreen />);
    expect(await screen.findByRole('heading', { level: 1, name: 'Share your location on visits?' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Never' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Only while I travel to a visit' })).toHaveAttribute('aria-pressed', 'false');
    const promises = container.querySelector('[data-el="PRAC-LOCATION-PROMISES"]') as HTMLElement;
    expect(within(promises).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      'The coordinator sees your estimated arrival, not a trail.',
      'It stops when you arrive.',
      'It is not used to time or rank you.',
    ]);
    expect(screen.getByText('You can change this at any time on this screen.')).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/in Settings/);
    expect(screen.getByRole('button', { name: 'Save my choice' })).toBeEnabled();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('shows a shimmer while it opens', async () => {
    render(<LocationScreen />);
    expect(screen.getByRole('status')).toHaveTextContent('Opening your choice.');
    await screen.findByRole('heading', { level: 1 });
  });

  it('saves the choice, and says so', async () => {
    render(<LocationScreen />);
    await userEvent.click(await screen.findByRole('button', { name: 'Only while I travel to a visit' }));
    await userEvent.click(screen.getByRole('button', { name: 'Save my choice' }));
    expect(await screen.findByText('Your choice is saved.')).toBeInTheDocument();
    expect(screen.getByText('Your choice is saved.').closest('[role="status"]')).not.toBeNull();
    expect(sent('PUT', '/api/bff/practitioner/settings')?.body).toEqual({ location: 'travel' });
    expect(screen.getByRole('button', { name: 'Only while I travel to a visit' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('says it could not save, and does not say it is saved', async () => {
    server.use(http.put('/api/bff/practitioner/settings', () => HttpResponse.json({ code: 'exception' }, { status: 502 })));
    render(<LocationScreen />);
    await userEvent.click(await screen.findByRole('button', { name: 'Save my choice' }));
    expect(await screen.findByText('We could not save that. Try again.')).toBeInTheDocument();
    expect(screen.queryByText('Your choice is saved.')).not.toBeInTheDocument();
  });
});
