import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { resetCsrfCache } from '@/lib/advisor/browser';
import { runAxe } from '@/test/a11y';
import { byEl } from '@/test/el';
import { MAP_VIEW } from '@/test/fixtures/map';
import { BLANK_CASE, CASE_ETAG } from '@/test/msw/handlers/advisor';
import { server } from '@/test/msw/server';
import { MapScreen } from './MapScreen';
import { PostcodeNotFound } from './PostcodeStates';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

// The postcode typed again in place, and the two extra next steps of the not-found state (MapWeb 3).

describe('PostcodeNotFound: search again (MapWeb 3)', () => {
  it('has no field unless the screen can try a postcode', () => {
    render(<PostcodeNotFound caseId="4821" onAskClinical={vi.fn()} />);
    expect(screen.queryByLabelText('Postcode')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Search again' })).toBeNull();
  });

  it('offers to phone a service that is known to have space, by way of the board', () => {
    render(<PostcodeNotFound caseId="4821" onAskClinical={vi.fn()} />);
    expect(screen.getByRole('link', { name: 'Phone a service you know has space' })).toHaveAttribute('href', '/advisor/board');
  });

  it('sends what was typed, once, and says in words when the postcode was not kept', async () => {
    const user = userEvent.setup();
    const onSearchAgain = vi.fn().mockResolvedValue('invalid');
    render(<PostcodeNotFound caseId="4821" onAskClinical={vi.fn()} onSearchAgain={onSearchAgain} />);

    await user.type(screen.getByLabelText('Postcode'), 'DT4 8X');
    await user.click(byEl('ADV-POSTCODE-SEARCH-BTN'));

    expect(onSearchAgain).toHaveBeenCalledExactlyOnceWith('DT4 8X');
    const problem = await screen.findByRole('alert');
    expect(problem).toHaveTextContent('Enter a full postcode, like DT4 8XX.');
    expect(screen.getByLabelText('Postcode')).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByLabelText('Postcode')).toHaveAccessibleDescription('Enter a full postcode, like DT4 8XX.');
    // Pressed again, the old message goes while the new try is made.
    onSearchAgain.mockResolvedValue('failed');
    await user.click(byEl('ADV-POSTCODE-SEARCH-BTN'));
    expect(await screen.findByText('The postcode could not be tried. Try again.')).toBeInTheDocument();
  });

  it('has no axe violations with the field and a message', async () => {
    const user = userEvent.setup();
    const { container } = render(
      <main>
        <PostcodeNotFound caseId="4821" onAskClinical={vi.fn()} onSearchAgain={vi.fn().mockResolvedValue('invalid')} />
      </main>,
    );
    await user.click(byEl('ADV-POSTCODE-SEARCH-BTN'));
    await screen.findByRole('alert');
    expect((await runAxe(container)).violations).toEqual([]);
  });
});

describe('the map: search again saves the postcode and reads the options again', () => {
  const NOT_FOUND = { ...MAP_VIEW, notFound: true, options: [], patientArea: null, districts: [] };
  const CASE = { ...BLANK_CASE, referrerType: 'gp', ageBand: '80+', postcode: 'DT4', needs: ['frailty'], urgency: 'within-2-hrs', etag: CASE_ETAG };

  beforeEach(() => resetCsrfCache());

  it('a good postcode is saved with If-Match and the map is drawn from the new options', async () => {
    const user = userEvent.setup();
    let reads = 0;
    let saved: { ifMatch: string | null; body: unknown } | null = null;
    server.use(
      http.get('/api/bff/cases/:ref', () => HttpResponse.json(CASE)),
      http.get('/api/bff/cases/:ref/options', () => HttpResponse.json(++reads === 1 ? NOT_FOUND : MAP_VIEW)),
      http.put('/api/bff/cases/:ref', async ({ request }) => {
        saved = { ifMatch: request.headers.get('if-match'), body: await request.json() };
        return HttpResponse.json(CASE);
      }),
    );
    render(<MapScreen caseId="4821" />);

    await user.type(await screen.findByLabelText('Postcode'), 'dt4 8xx');
    await user.click(byEl('ADV-POSTCODE-SEARCH-BTN'));

    expect(await screen.findByRole('heading', { name: 'Options near DT4' })).toBeInTheDocument();
    expect(saved).toMatchObject({ ifMatch: CASE_ETAG, body: { postcode: 'DT4 8XX', needs: ['frailty'] } });
    expect(reads).toBe(2);
  });

  it('a case that is not complete offers no field (it could not be saved from here)', async () => {
    server.use(
      http.get('/api/bff/cases/:ref', () => HttpResponse.json({ ...CASE, needs: [] })),
      http.get('/api/bff/cases/:ref/options', () => HttpResponse.json(NOT_FOUND)),
    );
    render(<MapScreen caseId="4821" />);
    expect(await screen.findByRole('heading', { name: 'We could not find that postcode' })).toBeInTheDocument();
    expect(screen.queryByLabelText('Postcode')).toBeNull();
  });
});
