import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { resetCsrfCache } from '@/lib/advisor/browser';
import { OPTIONS_EMPTY_VIEW, OPTIONS_VIEW } from '@/test/fixtures/options';
import { server } from '@/test/msw/server';
import { MapScreen } from './MapScreen';
import { OptionsList } from './OptionsList';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

// W45: "Ask a clinical advisor" opens the dialog from every screen that offers it. The dialog reads the case
// itself, so the screens hold no case.

const CASE = {
  id: '4821',
  referrerType: 'gp',
  ageBand: '80+',
  postcode: 'DT4 8XX',
  needs: ['frailty'],
  urgency: 'within-2-hrs',
  scores: [{ method: 'news2', value: 2 }],
  openedAt: null,
  etag: null,
};

beforeEach(() => {
  resetCsrfCache();
  server.use(
    http.get('/api/bff/cases/:ref', () => HttpResponse.json(CASE)),
    http.get('/api/bff/clinical/summary', () => HttpResponse.json({ available: 2 })),
  );
});

describe('Ask a clinical advisor, from the options list', () => {
  it('opens the dialog from the footer button, with the number of options shown, and closes it on Cancel', async () => {
    const onAskClinical = vi.fn();
    render(<OptionsList caseId="4821" onAskClinical={onAskClinical} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Ask clinical advisor' }));
    expect(onAskClinical).toHaveBeenCalledTimes(1);
    expect(await screen.findByRole('dialog', { name: 'Ask a clinical advisor' })).toBeInTheDocument();
    expect(screen.getByText('80+ · DT4 · Frailty · Within 2 hrs')).toBeInTheDocument();
    expect(screen.getByText('NEWS2 2 · Options shown: 3')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('opens the dialog from the no-fit state, with no options shown', async () => {
    server.use(http.get('/api/bff/cases/:ref/options', () => HttpResponse.json(OPTIONS_EMPTY_VIEW)));
    render(<OptionsList caseId="4821" />);
    await userEvent.click(await screen.findByRole('button', { name: 'Ask a clinical advisor' }));
    expect(await screen.findByRole('dialog', { name: 'Ask a clinical advisor' })).toBeInTheDocument();
    expect(screen.getByText('NEWS2 2 · Options shown: 0')).toBeInTheDocument();
  });

  it('is not open until asked', async () => {
    render(<OptionsList caseId="4821" />);
    await screen.findByRole('heading', { name: "3 services meet this patient's criteria" });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    void OPTIONS_VIEW;
  });
});

describe('Ask a clinical advisor, from the map', () => {
  it('opens the dialog from the postcode-not-found state', async () => {
    server.use(http.get('/api/bff/cases/:ref/options', () => HttpResponse.json({ ...OPTIONS_VIEW, options: [], notSuitable: [], notFound: true })));
    render(<MapScreen caseId="4821" />);
    await userEvent.click(await screen.findByRole('button', { name: 'Ask a clinical advisor' }));
    expect(await screen.findByRole('dialog', { name: 'Ask a clinical advisor' })).toBeInTheDocument();
  });
});
