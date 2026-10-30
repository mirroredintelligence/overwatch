import { render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { resetCsrfCache } from '@/lib/advisor/browser';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { CaseSummary } from './CaseSummary';

const SAVED = {
  id: '4821',
  referrerType: 'ambulance-crew',
  ageBand: '80+',
  postcode: 'DT4 8XX',
  needs: ['fall-no-injury', 'frailty'],
  urgency: 'within-2-hrs',
  scores: [],
  openedAt: null,
  etag: 'W/"1"',
};

describe('CaseSummary (W13)', () => {
  it('shows the saved case on one line with an Edit link', async () => {
    server.use(http.get('/api/bff/cases/:ref', () => HttpResponse.json(SAVED)));
    resetCsrfCache();
    render(<CaseSummary caseId="4821" />);

    expect(await screen.findByText('80+ · DT4 8XX · Fall, Frailty · Within 2 hrs')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Edit' })).toHaveAttribute('href', '/advisor/case/4821');
  });

  it('shows nothing it cannot read, and does not break the page', async () => {
    server.use(http.get('/api/bff/cases/:ref', () => HttpResponse.json({ code: 'not-found' }, { status: 404 })));
    const { container } = render(<CaseSummary caseId="4821" />);

    await waitFor(() => expect(container.textContent).toBe(''));
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
