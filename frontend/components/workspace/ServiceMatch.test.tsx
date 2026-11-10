import { render, screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { beforeEach, describe, expect, it } from 'vitest';
import { resetCsrfCache } from '@/lib/advisor/browser';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { ServiceMatch } from './ServiceMatch';
import { useWorkspace, WorkspaceProvider } from './WorkspaceProvider';

// "Why it matches this patient" on the service page (AdvisorService board, DEC-1379): the service is checked at once
// when the criteria are already set, and says why it fits or why it does not. Neutral words only.

const BACK = '/api/bff/advisor-v2/services/svc-a/check';
const FITS = { serviceId: 'svc-a', fits: true, reasons: [], fitsNeeds: ['frailty'], warnings: ['Its figure is old.'], phone: null };
const NOT_FIT = { serviceId: 'svc-a', fits: false, reasons: ['Does not take dementia'], fitsNeeds: [], warnings: [], phone: null };

let posted: unknown[] = [];

beforeEach(() => {
  resetCsrfCache();
  posted = [];
  window.localStorage.clear();
});

function serve(answer: unknown, status = 200) {
  server.use(
    http.post(BACK, async ({ request }) => {
      posted.push(await request.json());
      return HttpResponse.json(answer as Record<string, unknown>, { status });
    }),
  );
}

// Sets the criteria first, then mounts the children, as arriving from the results does.
function Seeded({ children, complete }: { children: ReactNode; complete: boolean }) {
  const { setCriteria } = useWorkspace();
  const [ready, setReady] = useState(false);
  const done = useRef(false);
  useEffect(() => {
    if (done.current) return;
    done.current = true;
    if (complete) setCriteria({ age: '65-79', postcode: 'DT4 8XX', needs: ['frailty'], urgency: 'today' });
    void Promise.resolve().then(() => setReady(true));
  }, [complete, setCriteria]);
  return ready ? children : null;
}

function renderMatch(complete = true) {
  return render(
    <WorkspaceProvider role="advisor">
      <Seeded complete={complete}>
        <ServiceMatch serviceId="svc-a" />
      </Seeded>
    </WorkspaceProvider>,
  );
}

describe('ServiceMatch', () => {
  it('checks the service once with the criteria set, and says why it matches', async () => {
    serve(FITS);
    renderMatch();
    expect(await screen.findByRole('heading', { name: 'Why it matches this patient' })).toBeInTheDocument();
    expect(posted).toEqual([{ postcode: 'DT4 8XX', ageBand: '65-79', needs: ['frailty'], urgency: 'today' }]);
    const panel = screen.getByRole('region', { name: 'Match with this patient' });
    expect(within(panel).getByText('Age 65 to 79 · Accepted')).toBeInTheDocument();
    expect(within(panel).getByText('Need: Frailty · Accepted')).toBeInTheDocument();
    expect(within(panel).getByText('DT4 is inside the coverage area · Covered')).toBeInTheDocument();
    expect(within(panel).getByText('Its figure is old.')).toBeInTheDocument();
  });

  it('says why it does not match, with the reasons and no "matches" rows', async () => {
    serve(NOT_FIT);
    renderMatch();
    expect(await screen.findByRole('heading', { name: 'Why it does not match this patient' })).toBeInTheDocument();
    expect(screen.getByText('Does not take dementia')).toBeInTheDocument();
    expect(screen.queryByText(/Accepted/)).toBeNull();
  });

  it('shows nothing and checks nothing when no criteria are set', async () => {
    serve(FITS);
    renderMatch(false);
    await Promise.resolve();
    expect(screen.queryByRole('region', { name: 'Match with this patient' })).toBeNull();
    expect(posted).toHaveLength(0);
  });

  it('shows nothing, and never a match, when the check fails', async () => {
    serve({ code: 'exception' }, 502);
    renderMatch();
    await screen.findByText('Checking this patient against the service.').catch(() => undefined);
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.queryByRole('region', { name: 'Match with this patient' })).toBeNull();
    expect(screen.queryByText(/matches this patient/)).toBeNull();
  });

  it('has no accessibility violations', async () => {
    serve(FITS);
    const { container } = renderMatch();
    await screen.findByRole('heading', { name: 'Why it matches this patient' });
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
