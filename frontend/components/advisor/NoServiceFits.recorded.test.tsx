import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { resetCsrfCache } from '@/lib/advisor/browser';
import { BLANK_CASE, resetSeenAdvisorRequests, seenCasePuts } from '@/test/msw/handlers/advisor';
import { server } from '@/test/msw/server';
import { NoServiceFits } from './NoServiceFits';

// "Widen the time" saves the case again (W16). The back end keeps the postcode district only and
// refuses a change to scores it holds, so the save leaves the postcode out, repeats the scores, and
// carries a key.

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

const WITHIN_2: Record<string, unknown> = {
  ...BLANK_CASE,
  referrerType: 'gp',
  ageBand: '80+',
  postcode: 'DT4',
  needs: ['frailty'],
  urgency: 'within-2-hrs',
  scores: [{ method: 'news2', value: 2 }],
};

beforeEach(() => {
  resetCsrfCache();
  resetSeenAdvisorRequests();
});

describe('widen the time (W16)', () => {
  it('saves the case with today, no postcode, the recorded scores and a key', async () => {
    server.use(http.get('/api/bff/cases/:ref', () => HttpResponse.json(WITHIN_2)));
    const user = userEvent.setup();
    render(<NoServiceFits caseId="case-1" onWidened={vi.fn()} onAskClinical={vi.fn()} />);

    await user.click(await screen.findByRole('button', { name: /Widen the time/ }));

    await waitFor(() => expect(seenCasePuts).toHaveLength(1));
    const body = seenCasePuts[0]?.body as Record<string, unknown>;
    expect(body).toEqual({
      referrerType: 'gp',
      ageBand: '80+',
      needs: ['frailty'],
      urgency: 'today',
      scores: [{ method: 'news2', value: 2 }],
    });
    expect(seenCasePuts[0]?.key).toMatch(/^[A-Za-z0-9_-]{8,64}$/);
  });

  it('is not offered for a planned or today case', async () => {
    server.use(http.get('/api/bff/cases/:ref', () => HttpResponse.json({ ...WITHIN_2, urgency: 'planned' })));
    render(<NoServiceFits caseId="case-1" onWidened={vi.fn()} onAskClinical={vi.fn()} />);

    await screen.findByRole('heading', { name: 'No service fits right now' });
    await waitFor(() => expect(screen.queryByRole('button', { name: /Widen the time/ })).toBeNull());
  });
});
