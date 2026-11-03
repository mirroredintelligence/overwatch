import { render, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { resetCsrfCache } from '@/lib/advisor/browser';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { CaseSummary } from './CaseSummary';

const SAVED = {
  id: '4821',
  reference: '4821',
  closed: false,
  closedAt: null,
  outcome: null,
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
  it('shows the saved case as the pinned patient card with an Edit needs link', async () => {
    server.use(http.get('/api/bff/cases/:ref', () => HttpResponse.json(SAVED)));
    resetCsrfCache();
    render(<CaseSummary caseId="4821" />);

    const card = await screen.findByRole('region', { name: 'This patient' });
    expect(within(card).getByText('80+ · DT4 8XX')).toBeInTheDocument();
    expect(within(card).getByText('Fall, no injury')).toBeInTheDocument();
    expect(within(card).getByText('Frailty')).toBeInTheDocument();
    expect(within(card).getByText('Within 2 hrs')).toBeInTheDocument();
    expect(within(card).getByRole('link', { name: 'Edit needs' })).toHaveAttribute('href', '/advisor/case/4821');
  });

  it('carries the referrer scores onto the card', async () => {
    server.use(
      http.get('/api/bff/cases/:ref', () => HttpResponse.json({ ...SAVED, scores: [{ method: 'news2', value: 2 }] })),
    );
    resetCsrfCache();
    render(<CaseSummary caseId="4821" />);

    expect(await screen.findByText('NEWS2 2')).toBeInTheDocument();
  });

  it('shows nothing it cannot read, and does not break the page', async () => {
    server.use(http.get('/api/bff/cases/:ref', () => HttpResponse.json({ code: 'not-found' }, { status: 404 })));
    const { container } = render(<CaseSummary caseId="4821" />);

    await waitFor(() => expect(container.textContent).toBe(''));
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
