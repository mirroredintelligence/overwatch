import { render, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { AskClinicalPanel, summaryOfCase } from './AskClinicalPanel';
import type { CaseView } from '@/lib/advisor/codes';

const CASE: CaseView = {
  id: 'case-4821',
  referrerType: 'gp',
  ageBand: '80+',
  postcode: 'DT4 8XX',
  needs: ['fall-no-injury', 'frailty'],
  urgency: 'within-2-hrs',
  scores: [
    { method: 'news2', value: 2 },
    { method: 'cfs', value: 6 },
  ],
  openedAt: null,
  etag: null,
};

describe('summaryOfCase', () => {
  it('reduces the case to what the dialog shows: age band, the postcode district only, needs, urgency, NEWS2 and the frailty scale', () => {
    expect(summaryOfCase(CASE)).toEqual({ ageBand: '80+', district: 'DT4', needs: ['Fall', 'Frailty'], within: 'Within 2 hrs', news2: 2, frailtyScale: 6 });
  });

  it('leaves out what the case does not hold', () => {
    expect(summaryOfCase({ ...CASE, ageBand: null, postcode: null, needs: [], urgency: null, scores: [] })).toEqual({
      ageBand: null,
      district: null,
      needs: [],
      within: null,
      news2: null,
      frailtyScale: null,
    });
  });
});

describe('AskClinicalPanel', () => {
  it('reads the case and opens the dialog with its summary and the number of options shown', async () => {
    server.use(http.get('/api/bff/cases/case-4821', () => HttpResponse.json(CASE)), http.get('/api/bff/clinical/summary', () => HttpResponse.json({ available: 1 })));
    const { container } = render(<AskClinicalPanel caseRef="case-4821" optionsShown={3} onClose={() => undefined} />);
    expect(await screen.findByText('80+ · DT4 · Fall, Frailty · Within 2 hrs')).toBeInTheDocument();
    expect(screen.getByText('NEWS2 2 · Frailty scale 6 · Options shown: 3')).toBeInTheDocument();
    expect(screen.queryByText('DT4 8XX')).not.toBeInTheDocument();
    expect(await screen.findByText('1 clinical advisor available')).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('says the summary could not be read when the case cannot be read, and still opens the dialog', async () => {
    server.use(http.get('/api/bff/cases/case-4821', () => HttpResponse.json({ code: 'exception' }, { status: 503 })), http.get('/api/bff/clinical/summary', () => HttpResponse.json({ available: 1 })));
    render(<AskClinicalPanel caseRef="case-4821" optionsShown={0} onClose={() => undefined} />);
    expect(await screen.findByText('The case summary could not be read.')).toBeInTheDocument();
    expect(screen.getByRole('dialog', { name: 'Ask a clinical advisor' })).toBeInTheDocument();
  });
});
