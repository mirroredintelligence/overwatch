// Tests for the flat results list (AdvisorResults and AdvisorMap boards, DEC-1379). jsdom has no layout, so the height the
// list has to fill is stubbed: ResizeObserver reports once when it starts watching, and clientHeight of the viewport
// is the value the test sets. How the rows look at that height is for a browser.

import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import type { FoundService } from '@/lib/advisor/v2/find';
import { ResultsList } from './ResultsList';

const viewport = { height: 0 };

class FixedObserver {
  private readonly notify: () => void;
  constructor(notify: () => void) {
    this.notify = notify;
  }
  observe(): void {
    this.notify();
  }
  disconnect(): void {}
}

beforeEach(() => {
  viewport.height = 0;
  vi.stubGlobal('ResizeObserver', FixedObserver);
  Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
    configurable: true,
    get(this: HTMLElement) {
      return this.getAttribute('data-el') === 'WS-RESULTS-VIEWPORT' ? viewport.height : 0;
    },
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  Reflect.deleteProperty(HTMLElement.prototype, 'clientHeight');
});

function service(n: number, over: Partial<FoundService> = {}): FoundService {
  return {
    serviceId: `svc-${n}`,
    name: `Service ${n}`,
    category: 'urgent-community-response',
    status: 'accepting',
    effectiveAvailable: n,
    overBy: null,
    unitLabel: 'visits free',
    dataAgeSeconds: 600,
    reportedAt: null,
    nextDueAt: null,
    cadence: null,
    overdue: false,
    staleWarning: false,
    figureUnavailable: false,
    lastFigure: null,
    criteriaVersion: 1,
    fits: [],
    warnings: [],
    phone: null,
    travel: null,
    position: null,
    coverage: { districts: [], circle: null },
    ...over,
  };
}

const SEVEN = [1, 2, 3, 4, 5, 6, 7].map((n) => service(n));
// Five rows of 72px with four gaps of 10px.
const FIVE_ROWS = 5 * 72 + 4 * 10;
const count = () => screen.getByText(/ of \d+$/).textContent;
const names = () => within(screen.getByRole('list', { name: 'Matching services' })).getAllByRole('link').map((link) => link.textContent?.match(/^Service \d/)?.[0]);

describe('ResultsList (WS-RES)', () => {
  it('WS-RES-T01 with a height for five rows it shows five rows and "1–5 of 7"; Next shows the last two and "6–7 of 7"; Previous goes back', async () => {
    viewport.height = FIVE_ROWS;
    const user = userEvent.setup();
    render(<ResultsList services={SEVEN} onOpen={vi.fn()} />);
    expect(names()).toEqual(['Service 1', 'Service 2', 'Service 3', 'Service 4', 'Service 5']);
    expect(count()).toBe('1–5 of 7');
    await user.click(screen.getByRole('button', { name: 'Next page' }));
    expect(names()).toEqual(['Service 6', 'Service 7']);
    expect(count()).toBe('6–7 of 7');
    await user.click(screen.getByRole('button', { name: 'Previous page' }));
    expect(count()).toBe('1–5 of 7');
  });

  it('WS-RES-T02 Previous is disabled on the first page and Next on the last', async () => {
    viewport.height = FIVE_ROWS;
    const user = userEvent.setup();
    render(<ResultsList services={SEVEN} onOpen={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'Previous page' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Next page' })).toBeEnabled();
    await user.click(screen.getByRole('button', { name: 'Next page' }));
    expect(screen.getByRole('button', { name: 'Previous page' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Next page' })).toBeDisabled();
  });

  it('WS-RES-T03 the number of rows follows the height, and is at least one', () => {
    viewport.height = 3 * 72 + 2 * 10;
    const first = render(<ResultsList services={SEVEN} onOpen={vi.fn()} />);
    expect(count()).toBe('1–3 of 7');
    first.unmount();
    viewport.height = 20;
    render(<ResultsList services={SEVEN} onOpen={vi.fn()} />);
    expect(count()).toBe('1–1 of 7');
  });

  it('WS-RES-T04 the compact rows fit by their own height (64px and 8px)', () => {
    viewport.height = 4 * 64 + 3 * 8;
    render(<ResultsList services={SEVEN} compact onOpen={vi.fn()} />);
    expect(count()).toBe('1–4 of 7');
  });

  it('WS-RES-T05 when the height cannot be measured every service is shown on one page', () => {
    render(<ResultsList services={SEVEN} onOpen={vi.fn()} />);
    expect(names()).toHaveLength(7);
    expect(count()).toBe('1–7 of 7');
    expect(screen.getByRole('button', { name: 'Previous page' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Next page' })).toBeDisabled();
  });

  it('WS-RES-T06 a different list (another order) starts again at the first page', async () => {
    viewport.height = FIVE_ROWS;
    const user = userEvent.setup();
    const view = render(<ResultsList services={SEVEN} onOpen={vi.fn()} />);
    await user.click(screen.getByRole('button', { name: 'Next page' }));
    expect(count()).toBe('6–7 of 7');
    view.rerender(<ResultsList services={[...SEVEN].reverse()} onOpen={vi.fn()} />);
    expect(count()).toBe('1–5 of 7');
    expect(names()[0]).toBe('Service 7');
  });

  it('WS-RES-T07 no services shows an empty list and no pager', () => {
    render(<ResultsList services={[]} onOpen={vi.fn()} />);
    expect(screen.queryByRole('link')).toBeNull();
    expect(screen.queryByRole('navigation', { name: 'Matching services pages' })).toBeNull();
  });

  it('WS-RES-T08 following a row calls onOpen with that service; the row links to its page with the id encoded', async () => {
    const onOpen = vi.fn();
    const user = userEvent.setup();
    render(<ResultsList services={[service(1, { serviceId: 'a/b c' })]} onOpen={onOpen} />);
    const row = screen.getByRole('link', { name: /^Service 1/ });
    expect(row).toHaveAttribute('href', '/advisor/v2/services/a%2Fb%20c');
    await user.click(row);
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onOpen.mock.calls[0]?.[0]).toMatchObject({ serviceId: 'a/b c' });
  });

  it('WS-RES-T09 the status is always a word; an over-capacity service shows how far above normal, and never an invented figure', () => {
    render(
      <ResultsList
        services={[
          service(1, { status: 'over-capacity', overBy: 2, effectiveAvailable: 0 }),
          service(2, { status: 'limited' }),
          service(3, { status: 'not-updated', figureUnavailable: true, dataAgeSeconds: null, effectiveAvailable: null }),
        ]}
        onOpen={vi.fn()}
      />,
    );
    const rows = screen.getAllByRole('link');
    expect(within(rows[0]!).getByText('Over capacity')).toBeInTheDocument();
    expect(within(rows[0]!).getByText('+2')).toBeInTheDocument();
    expect(within(rows[0]!).getByText('Above normal')).toBeInTheDocument();
    expect(within(rows[1]!).getByText('Limited')).toBeInTheDocument();
    expect(within(rows[2]!).getByText('Not updated')).toBeInTheDocument();
    expect(within(rows[2]!).getByText('Unknown')).toBeInTheDocument();
    expect(within(rows[2]!).getByText(/no report yet/)).toBeInTheDocument();
  });

  it('WS-RES-T10 the compact row shows the group, the status word and its figure in one chip, and no Open button', () => {
    render(<ResultsList services={[service(4)]} compact onOpen={vi.fn()} />);
    const row = screen.getByRole('link', { name: /^Service 4/ });
    expect(within(row).getByText('Urgent community response')).toBeInTheDocument();
    expect(within(row).getByText('Accepting · 4')).toBeInTheDocument();
    expect(within(row).queryByText('Open')).toBeNull();
  });

  it('WS-RES-T11 the list passes runAxe, in both sizes, and no element has a style attribute', async () => {
    viewport.height = FIVE_ROWS;
    const full = render(<ResultsList services={SEVEN} onOpen={vi.fn()} />);
    expect(await runAxe(full.container)).toHaveNoViolations();
    expect(full.container.querySelector('[style]')).toBeNull();
    full.unmount();
    const compact = render(<ResultsList services={SEVEN} compact onOpen={vi.fn()} />);
    expect(await runAxe(compact.container)).toHaveNoViolations();
    expect(compact.container.querySelector('[style]')).toBeNull();
  });
});
