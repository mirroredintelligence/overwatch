import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { NotSuitable } from '@/lib/advisor/v2/find';
import { runAxe } from '@/test/a11y';
import { NotSuitableList } from './NotSuitableList';

// The not-suitable list (AdvisorWhy board, DEC-1379): every service that failed, each with every reason and its status.
// jsdom has no layout, so the measured height of the list is mocked; contrast and the fit of rows are not checked here.

function item(n: number, overrides: Partial<NotSuitable> = {}): NotSuitable {
  return { serviceId: `svc-${n}`, name: `Service ${n}`, category: 'inpatient-beds', status: 'not-accepting', reasons: [`Reason for ${n}`], position: null, ...overrides };
}

const hrefOf = (id: string) => `/advisor/v2/services/${id}`;

function renderList(items: readonly NotSuitable[], extra: { suitableCount?: number; summaryLine?: string | null } = {}) {
  return render(
    <NotSuitableList items={items} suitableCount={extra.suitableCount ?? 7} summaryLine={extra.summaryLine === undefined ? '65 to 79 · DT4' : extra.summaryLine} serviceHref={hrefOf} backHref="/advisor/v2/results" />,
  );
}

let height = 0;
const originalClientHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientHeight');

beforeEach(() => {
  height = 0;
  Object.defineProperty(HTMLElement.prototype, 'clientHeight', { configurable: true, get: () => height });
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      disconnect() {}
      unobserve() {}
    },
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  if (originalClientHeight !== undefined) Object.defineProperty(HTMLElement.prototype, 'clientHeight', originalClientHeight);
});

describe('NotSuitableList', () => {
  it('WS-NSL-T01 the heading says how many services were not suitable, in the plural', () => {
    renderList([item(1), item(2), item(3)]);
    expect(screen.getByRole('heading', { level: 1, name: '3 services were not suitable for this patient' })).toBeInTheDocument();
  });

  it('WS-NSL-T02 the heading is singular for one service', () => {
    renderList([item(1)]);
    expect(screen.getByRole('heading', { level: 1, name: '1 service was not suitable for this patient' })).toBeInTheDocument();
  });

  it('WS-NSL-T03 the sub line reads the summary then that nothing is hidden, and omits the summary when null', () => {
    const { unmount } = renderList([item(1)]);
    expect(screen.getByText('65 to 79 · DT4. Nothing is hidden: every service is either on the results list or here with its reason.')).toBeInTheDocument();
    unmount();
    renderList([item(1)], { summaryLine: null });
    expect(screen.getByText('Nothing is hidden: every service is either on the results list or here with its reason.')).toBeInTheDocument();
  });

  it('WS-NSL-T04 each row has the name, the category, every reason on its own line and the status as a word', () => {
    renderList([item(1, { category: 'inpatient-beds', status: 'over-capacity', reasons: ['Outside the travel distance', 'Over capacity: 2 beds above normal'] }), item(2, { status: 'limited' })]);
    const rows = screen.getAllByRole('listitem');
    expect(rows).toHaveLength(2);
    const first = within(rows[0]!);
    expect(first.getByText('Service 1')).toBeInTheDocument();
    expect(first.getByText('Inpatient beds')).toBeInTheDocument();
    const reasons = first.getAllByTestId('reason');
    expect(reasons.map((node) => node.textContent)).toEqual(['Outside the travel distance', 'Over capacity: 2 beds above normal']);
    expect(first.getByText('Over capacity')).toBeInTheDocument();
    expect(within(rows[1]!).getByText('Limited')).toBeInTheDocument();
  });

  it('WS-NSL-T05 the name links to the service page', () => {
    renderList([item(1), item(2)]);
    expect(screen.getByRole('link', { name: 'Service 2' })).toHaveAttribute('href', '/advisor/v2/services/svc-2');
  });

  it('WS-NSL-T06 with a measured height that holds two rows it pages with Previous and Next and an a-b of N count', () => {
    height = 200;
    renderList([item(1), item(2), item(3), item(4), item(5)]);
    expect(screen.getByText('1–2 of 5')).toBeInTheDocument();
    expect(screen.getAllByRole('listitem')).toHaveLength(2);
    const previous = screen.getByRole('button', { name: 'Previous page' });
    const next = screen.getByRole('button', { name: 'Next page' });
    expect(previous).toBeDisabled();
    fireEvent.click(next);
    expect(screen.getByText('3–4 of 5')).toBeInTheDocument();
    expect(screen.getByText('Service 3')).toBeInTheDocument();
    fireEvent.click(next);
    expect(screen.getByText('5–5 of 5')).toBeInTheDocument();
    expect(next).toBeDisabled();
    fireEvent.click(previous);
    expect(screen.getByText('3–4 of 5')).toBeInTheDocument();
  });

  it('WS-NSL-T07 a row with more reasons takes more of the height, so fewer rows fit', () => {
    height = 200;
    renderList([item(1, { reasons: ['One', 'Two', 'Three', 'Four', 'Five'] }), item(2), item(3)]);
    expect(screen.getByText('1–1 of 3')).toBeInTheDocument();
  });

  it('WS-NSL-T08 with no measured height every row is shown and there are no paging buttons', () => {
    renderList([item(1), item(2), item(3), item(4)]);
    expect(screen.getAllByRole('listitem')).toHaveLength(4);
    expect(screen.getByText('1–4 of 4')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Next page' })).not.toBeInTheDocument();
  });

  it('WS-NSL-T09 the back link names the suitable count, singular for one, and goes to backHref', () => {
    const { unmount } = renderList([item(1)], { suitableCount: 7 });
    expect(screen.getByRole('link', { name: 'Back to the 7 suitable services' })).toHaveAttribute('href', '/advisor/v2/results');
    unmount();
    renderList([item(1)], { suitableCount: 1 });
    expect(screen.getByRole('link', { name: 'Back to the 1 suitable service' })).toHaveAttribute('href', '/advisor/v2/results');
  });

  it('WS-NSL-T10 with no items it says every service takes this patient and keeps the back link', () => {
    renderList([]);
    expect(screen.getByText('Every service takes this patient. Nothing is hidden.')).toBeInTheDocument();
    expect(screen.queryByRole('listitem')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Back to the 7 suitable services' })).toBeInTheDocument();
  });

  it('WS-NSL-T11 has no axe violations with rows and when empty', async () => {
    const { container, unmount } = renderList([item(1, { reasons: ['A', 'B'] }), item(2, { status: 'over-capacity' })]);
    expect(await runAxe(container)).toHaveNoViolations();
    unmount();
    const empty = renderList([]);
    expect(await runAxe(empty.container)).toHaveNoViolations();
  });
});
