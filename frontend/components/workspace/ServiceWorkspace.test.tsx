import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { ServiceWorkspace } from './ServiceWorkspace';
import { WorkspaceProvider, useWorkspace } from './WorkspaceProvider';

// The service page inside the workspace (DEC-1376, WS-SVC): the frame around the existing ServiceDetail, and the
// assistant's service turn. ServiceDetail is mocked; the provider and the frame are real. Tests use neutral words only.

const { store, storeMode } = vi.hoisted(() => ({
  store: new Map<string, unknown>(),
  storeMode: { throws: false },
}));

// An in-memory tenantStore, the same shape the provider's own tests use.
vi.mock('@/lib/storage/tenantStore', () => ({
  tenantStore: {
    get: (name: string, validate: (value: unknown) => boolean) => {
      if (storeMode.throws) throw new Error('storage blocked');
      const value = store.get(name);
      return value !== undefined && validate(value) ? value : undefined;
    },
    set: (name: string, value: unknown) => {
      if (storeMode.throws) throw new Error('storage blocked');
      store.set(name, value);
      return true;
    },
    remove: (name: string) => {
      store.delete(name);
    },
    names: () => [...store.keys()],
    clear: () => {
      const count = store.size;
      store.clear();
      return count;
    },
  },
}));

// The existing detail component is replaced by a stub that shows the id and the two labels it was given.
vi.mock('@/components/service/ServiceDetail', () => ({
  ServiceDetail: (props: { serviceId: string; backHref: string; backLabel: string; rootLabel: string }) => (
    <div data-testid="service-detail">
      <span>{props.serviceId}</span>
      <span>{props.backLabel}</span>
      <span>{props.rootLabel}</span>
      <span>{props.backHref}</span>
    </div>
  ),
}));

const RESULTS_HREF = '/advisor/v2?mode=find&view=list';
const SERVICE_REPLY = 'Here is the service. If the call allows, check that its figure is current.';

// Makes an earlier results turn and opens Alpha, then mounts the children. The children mount only after both
// updates are in, so the service turn sees the opened service and an earlier entry (as a real click path does).
function Prepared({ children }: { children: ReactNode }) {
  const { visit, remember } = useWorkspace();
  const [ready, setReady] = useState(false);
  const done = useRef(false);
  useEffect(() => {
    if (done.current) return;
    done.current = true;
    visit('advisor.results', { count: 3, order: 'travel' });
    remember({ serviceName: 'Alpha', updated: '1 hr 55 min ago', stale: false, noReport: false });
    void Promise.resolve().then(() => setReady(true));
  }, [remember, visit]);
  return ready ? children : null;
}

function renderService(children: ReactNode) {
  return render(<WorkspaceProvider role="advisor-v2">{children}</WorkspaceProvider>);
}

beforeEach(() => {
  store.clear();
  storeMode.throws = false;
});

afterEach(() => {
  cleanup();
});

describe('ServiceWorkspace', () => {
  it('WS-SVC-T01 renders ServiceDetail for the id inside the frame titled "Service detail"', () => {
    renderService(<ServiceWorkspace serviceId="svc-a" />);
    expect(screen.getByText('Service detail')).toBeInTheDocument();
    const main = screen.getByRole('main', { name: 'Canvas' });
    const detail = within(main).getByTestId('service-detail');
    expect(detail).toHaveTextContent('svc-a');
    expect(within(detail).getByText('Back to results')).toBeInTheDocument();
    expect(within(detail).getByText('Find a service')).toBeInTheDocument();
  });

  it('WS-SVC-T02 the frame back link is named "Back" and points to the results list', () => {
    renderService(<ServiceWorkspace serviceId="svc-a" />);
    expect(screen.getByRole('link', { name: 'Back' })).toHaveAttribute('href', RESULTS_HREF);
  });

  it('WS-SVC-T03 with an earlier results turn and an opened service, the thread shows the echo and the service reply', async () => {
    renderService(
      <Prepared>
        <ServiceWorkspace serviceId="svc-a" />
      </Prepared>,
    );
    expect(await screen.findByText('Open Alpha')).toBeInTheDocument();
    expect(
      screen.getByText('Here is Alpha. Last updated 1 hr 55 min ago. If the call allows, check that it is current.'),
    ).toBeInTheDocument();
    expect(screen.queryByText(SERVICE_REPLY)).not.toBeInTheDocument();
  });

  it('WS-SVC-T04 on a hard load the thread shows only the service reply and a "Back to results" chip', () => {
    renderService(<ServiceWorkspace serviceId="svc-a" />);
    const log = screen.getByRole('log', { name: 'Conversation' });
    expect(log.children).toHaveLength(1);
    expect(within(log).getByText(SERVICE_REPLY)).toBeInTheDocument();
    expect(log.querySelector('[data-from="person"]')).toBeNull();
    expect(screen.getByRole('link', { name: 'Back to results' })).toHaveAttribute('href', RESULTS_HREF);
  });
});
