import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { resetCsrfCache } from '@/lib/advisor/browser';
import { server } from '@/test/msw/server';
import { OptionsList } from './OptionsList';

// KI-768: asking a clinical advisor from one service's card is asking about THAT service, so the request
// records it and the advice can name it. Asking from the list's footer is asking about the case.

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));
// A card's own booking control is out of scope here: it offers one button that asks, as a declined or
// withdrawn booking does.
vi.mock('./OptionBooking', () => ({
  OptionBooking: ({ option, onAskClinical }: { option: { name: string }; onAskClinical?: () => void }) => (
    <button type="button" onClick={() => onAskClinical?.()}>{`Ask about ${option.name}`}</button>
  ),
}));

const CASE = { id: '4821', referrerType: 'gp', ageBand: '80+', postcode: 'DT4', needs: ['frailty'], urgency: 'within-2-hrs', scores: [], scoreCorrections: 0, openedAt: null, etag: null };
const posted: unknown[] = [];

beforeEach(() => {
  resetCsrfCache();
  posted.length = 0;
  server.use(
    http.get('/api/bff/cases/:ref', () => HttpResponse.json(CASE)),
    http.get('/api/bff/clinical/summary', () => HttpResponse.json({ available: 2 })),
    http.post('/api/bff/cases/:ref/clinical-requests', async ({ request }) => {
      posted.push(await request.json());
      return HttpResponse.json({ requestId: 'req-9001' }, { status: 201 });
    }),
  );
});

describe('the service under consideration (KI-768)', () => {
  it('asked from a service\'s card: the dialog names the service and the request sends its id', async () => {
    const user = userEvent.setup();
    render(<OptionsList caseId="4821" />);

    await user.click(await screen.findByRole('button', { name: 'Ask about Hospital at home' }));
    expect(await screen.findByText('About: Hospital at home')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Unsure of urgency' }));
    await user.click(screen.getByRole('button', { name: 'Call clinical advisor' }));

    await vi.waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0]).toEqual({ urgency: 'now', why: 'unsure-of-urgency', service: 'svc-hospital-at-home' });
  });

  it('asked from the footer: about the case as a whole, so no service is named or sent', async () => {
    const user = userEvent.setup();
    render(<OptionsList caseId="4821" />);

    await user.click(await screen.findByRole('button', { name: 'Ask clinical advisor' }));
    expect(await screen.findByRole('dialog', { name: 'Ask a clinical advisor' })).toBeInTheDocument();
    expect(screen.queryByText(/^About:/)).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Unsure of urgency' }));
    await user.click(screen.getByRole('button', { name: 'Call clinical advisor' }));

    await vi.waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0]).toEqual({ urgency: 'now', why: 'unsure-of-urgency' });
  });
});
